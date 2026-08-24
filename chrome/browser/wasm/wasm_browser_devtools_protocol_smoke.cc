// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "chrome/browser/wasm/wasm_browser_devtools_protocol_smoke.h"

#include <cstdio>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/json/json_reader.h"
#include "base/values.h"
#include "build/build_config.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/devtools_agent_host.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"

#if !BUILDFLAG(IS_WASM)
#error "wasm_browser_devtools_protocol_smoke.cc must only be built for WebAssembly"
#endif

namespace chrome {

namespace {

constexpr char kNetworkEnableCommand[] =
    R"({"id":1,"method":"Network.enable"})";
constexpr char kRuntimeEnableCommand[] =
    R"({"id":2,"method":"Runtime.enable"})";
constexpr char kRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(console.log('chromium-wasm-m8-devtools-console'),)json"
    R"json( typeof WebAssembly)","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,7,1,96,2,127,127,1,127,3,2,1,0,7,7,1,3,97,)json"
    R"json(100,100,0,0,10,9,1,7,0,32,0,32,1,106,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm validation failed');)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m);)json"
    R"json(const r=i.exports.add(20,22);if(r!==42)throw new Error('wasm add result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-add-42');)json"
    R"json(return 'wasm-add-42';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyMemoryRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,11,2,96,1,127,1,127,96,2,127,127,0,2,16,1,3,101,110,118,6,109,101,109,111,114,121,2,1,1,1,)json"
    R"json(3,3,2,0,1,7,16,2,4,114,101,97,100,0,0,5,119,114,105,116,101,0,1,10,19,2,7,0,32,0,40,2,0,11,9,0,32,0,32,1,54,2,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm memory validation failed');)json"
    R"json(const memory=new WebAssembly.Memory({initial:1,maximum:1});)json"
    R"json(if(memory.buffer.byteLength!==65536)throw new Error('wasm memory initial size was not 65536');)json"
    R"json(const view=new DataView(memory.buffer);view.setUint32(0,0x12345678,true);)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{memory}});)json"
    R"json(if(i.exports.read(0)!==0x12345678)throw new Error('wasm memory did not read JS write');)json"
    R"json(i.exports.write(4,0x0badf00d);)json"
    R"json(if(view.getUint32(4,true)!==0x0badf00d)throw new Error('JS did not read wasm memory write');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-memory-import-read-write');)json"
    R"json(return 'wasm-memory-import-read-write';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyTableRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,6,1,96,1,127,1,127,2,16,1,3,101,110,118,5,116,97,98,108,101,1,112,1,1,1,)json"
    R"json(3,3,2,0,0,7,8,1,4,99,97,108,108,0,1,9,7,1,0,65,0,11,1,0,10,19,2,7,0,32,0,65,1,106,11,9,0,32,0,65,0,17,0,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm table validation failed');)json"
    R"json(const table=new WebAssembly.Table({initial:1,maximum:1,element:'anyfunc'});)json"
    R"json(if(table.length!==1)throw new Error('wasm table initial size was not 1');)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{table}});)json"
    R"json(if(i.exports.call(41)!==42)throw new Error('wasm indirect call result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-table-import-indirect-call');)json"
    R"json(return 'wasm-table-import-indirect-call';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyTableGrowthRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,12,2,96,1,127,1,127,96,2,127,127,1,127,2,16,1,3,101,110,118,5,116,97,98,108,101,1,112,1,1,2,)json"
    R"json(3,3,2,0,1,7,15,2,4,97,100,100,49,0,0,4,99,97,108,108,0,1,9,7,1,0,65,0,11,1,0,10,19,2,7,0,32,0,65,1,106,11,9,0,32,0,32,1,17,0,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm table growth validation failed');)json"
    R"json(const table=new WebAssembly.Table({initial:1,maximum:2,element:'anyfunc'});)json"
    R"json(if(table.length!==1)throw new Error('wasm table initial size was not 1');)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{table}});)json"
    R"json(if(i.exports.call(41,0)!==42)throw new Error('wasm initial indirect call result was not 42');)json"
    R"json(if(table.grow(1,i.exports.add1)!==1)throw new Error('wasm table grow did not return 1');)json"
    R"json(if(table.length!==2)throw new Error('wasm table grown size was not 2');)json"
    R"json(if(table.get(1)!==i.exports.add1)throw new Error('wasm table grow did not initialize grown entry');)json"
    R"json(if(i.exports.call(41,1)!==42)throw new Error('wasm grown indirect call result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-table-growth-import-grown-indirect-call');)json"
    R"json(return 'wasm-table-growth-import-grown-indirect-call';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyMemoryGrowthRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,11,2,96,1,127,1,127,96,2,127,127,0,2,16,1,3,101,110,118,6,109,101,109,111,114,121,2,1,1,2,)json"
    R"json(3,3,2,0,1,7,16,2,4,114,101,97,100,0,0,5,119,114,105,116,101,0,1,10,19,2,7,0,32,0,40,2,0,11,9,0,32,0,32,1,54,2,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm memory growth validation failed');)json"
    R"json(const memory=new WebAssembly.Memory({initial:1,maximum:2});)json"
    R"json(if(memory.buffer.byteLength!==65536)throw new Error('wasm memory initial size was not 65536');)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{memory}});)json"
    R"json(const beforeGrowth=memory.buffer;if(memory.grow(1)!==1)throw new Error('wasm memory grow did not return 1');)json"
    R"json(const grownBuffer=memory.buffer;if(grownBuffer===beforeGrowth)throw new Error('wasm memory grow did not replace buffer');)json"
    R"json(if(beforeGrowth.byteLength!==0)throw new Error('wasm memory grow did not detach old buffer');)json"
    R"json(if(memory.buffer.byteLength!==131072)throw new Error('wasm memory grown size was not 131072');)json"
    R"json(const view=new DataView(memory.buffer);view.setUint32(65536,0x12345678,true);)json"
    R"json(if(i.exports.read(65536)!==0x12345678)throw new Error('wasm memory did not read JS post-growth write');)json"
    R"json(i.exports.write(65540,0x0badf00d);)json"
    R"json(if(view.getUint32(65540,true)!==0x0badf00d)throw new Error('JS did not read wasm post-growth memory write');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-memory-growth-import-post-growth-read-write');)json"
    R"json(return 'wasm-memory-growth-import-post-growth-read-write';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyExceptionRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,8,2,96,0,0,96,0,1,127,2,26,2,3,101,110,118,7,116,104,114,111,119,101,114,0,1,3,101,110,118,3,116,97,103,4,0,0,)json"
    R"json(3,2,1,1,7,7,1,3,114,117,110,0,1,10,13,1,11,0,6,127,16,0,7,0,65,42,11,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm exception validation failed');)json"
    R"json(const tag=new WebAssembly.Tag({parameters:[]});)json"
    R"json(const exception=new WebAssembly.Exception(tag,[]);)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{tag,thrower:()=>{throw exception}}});)json"
    R"json(if(i.exports.run()!==42)throw new Error('wasm exception catch result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-exception-imported-tag-js-throw-wasm-catch');)json"
    R"json(return 'wasm-exception-imported-tag-js-throw-wasm-catch';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,5,1,96,0,1,127,2,16,1,3,101,110,118,6,109,101,109,111,114,121,2,1,1,2,)json"
    R"json(3,2,1,0,7,8,1,4,103,114,111,119,0,0,10,8,1,6,0,65,1,64,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm memory grow opcode validation failed');)json"
    R"json(const memory=new WebAssembly.Memory({initial:1,maximum:2});)json"
    R"json(if(memory.buffer.byteLength!==65536)throw new Error('wasm memory initial size was not 65536');)json"
    R"json(const beforeGrowth=memory.buffer;const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{memory}});)json"
    R"json(if(i.exports.grow()!==1)throw new Error('wasm memory grow opcode did not return 1');)json"
    R"json(const grownBuffer=memory.buffer;if(grownBuffer===beforeGrowth)throw new Error('wasm memory grow opcode did not replace buffer');)json"
    R"json(if(beforeGrowth.byteLength!==0)throw new Error('wasm memory grow opcode did not detach old buffer');)json"
    R"json(if(grownBuffer.byteLength!==131072)throw new Error('wasm memory grow opcode size was not 131072');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-wasm-memory-grow-opcode-import-one-to-two-pages');)json"
    R"json(return 'wasm-memory-grow-opcode-import-one-to-two-pages';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyWasmTableGrowOpcodeRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,16,3,96,1,127,1,127,96,2,127,127,1,127,96,0,1,127,2,16,1,3,101,110,118,5,116,97,98,108,101,1,112,1,1,2,)json"
    R"json(3,4,3,0,1,2,7,22,3,4,97,100,100,49,0,0,4,99,97,108,108,0,1,4,103,114,111,119,0,2,9,7,1,0,65,0,11,1,0,)json"
    R"json(10,29,3,7,0,32,0,65,1,106,11,9,0,32,0,32,1,17,0,0,11,9,0,210,0,65,1,252,15,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm table grow opcode validation failed');)json"
    R"json(const table=new WebAssembly.Table({initial:1,maximum:2,element:'anyfunc'});)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{table}});)json"
    R"json(if(i.exports.call(41,0)!==42)throw new Error('wasm table grow opcode initial indirect call result was not 42');)json"
    R"json(if(i.exports.grow()!==1)throw new Error('wasm table grow opcode did not return 1');)json"
    R"json(if(table.length!==2)throw new Error('wasm table grow opcode size was not 2');)json"
    R"json(if(table.get(1)!==i.exports.add1)throw new Error('wasm table grow opcode did not initialize grown entry');)json"
    R"json(if(i.exports.call(41,1)!==42)throw new Error('wasm table grow opcode grown indirect call result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-wasm-table-grow-opcode-import-one-to-two-entries-indirect-call');)json"
    R"json(return 'wasm-table-grow-opcode-import-one-to-two-entries-indirect-call';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyWasmThrowRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,4,1,96,0,0,2,12,1,3,101,110,118,3,116,97,103,4,0,0,3,2,1,0,7,11,1,7,116,104,114,111,119,101,114,0,0,10,6,1,4,0,8,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm throw validation failed');)json"
    R"json(const tag=new WebAssembly.Tag({parameters:[]});)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{tag}});)json"
    R"json(let caught=false;try{i.exports.thrower();}catch(error){caught=error instanceof WebAssembly.Exception&&error.is(tag);})json"
    R"json(if(!caught)throw new Error('wasm throw did not escape as its imported tag');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-wasm-throw-imported-tag-js-catch');)json"
    R"json(return 'wasm-throw-imported-tag-js-catch';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyWasmThrowPayloadRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,8,2,96,1,127,0,96,0,0,2,12,1,3,101,110,118,3,116,97,103,4,0,0,3,2,1,1,7,11,1,7,116,104,114,111,119,101,114,0,0,10,8,1,6,0,65,42,8,0,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm typed throw validation failed');)json"
    R"json(const tag=new WebAssembly.Tag({parameters:['i32']});)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{tag}});)json"
    R"json(let caught=false;try{i.exports.thrower();}catch(error){caught=error instanceof WebAssembly.Exception&&error.is(tag)&&error.getArg(tag,0)===42;})json"
    R"json(if(!caught)throw new Error('wasm typed throw did not escape with payload 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-wasm-throw-imported-i32-tag-js-catch-payload-42');)json"
    R"json(return 'wasm-throw-imported-i32-tag-js-catch-payload-42';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyJsThrowPayloadRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(()=>{const b=new Uint8Array([)json"
    R"json(0,97,115,109,1,0,0,0,1,9,2,96,1,127,0,96,0,1,127,2,26,2,3,101,110,118,7,116,104,114,111,119,101,114,0,1,3,101,110,118,3,116,97,103,4,0,0,3,2,1,1,7,7,1,3,114,117,110,0,1,10,11,1,9,0,6,127,16,0,7,0,11,11]);)json"
    R"json(if(!WebAssembly.validate(b))throw new Error('wasm typed JS throw validation failed');)json"
    R"json(const tag=new WebAssembly.Tag({parameters:['i32']});)json"
    R"json(const m=new WebAssembly.Module(b);const i=new WebAssembly.Instance(m,{env:{tag,thrower:()=>{throw new WebAssembly.Exception(tag,[42]);}}});)json"
    R"json(if(i.exports.run()!==42)throw new Error('wasm typed JS throw catch result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-imported-i32-tag-js-throw-wasm-catch-payload-42');)json"
    R"json(return 'wasm-exception-imported-i32-tag-js-throw-wasm-catch-payload-42';})()","returnByValue":true,)json"
    R"json("allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kPageWebAssemblyInstantiateStreamingRuntimeEvaluateCommand[] =
    R"json({"id":3,"method":"Runtime.evaluate","params":{"expression":)json"
    R"json("(async()=>{const r=await WebAssembly.instantiateStreaming(fetch('data:application/wasm;base64,AGFzbQEAAAABBwFgAn9/AX8DAgEABwcBA2FkZAAACgkBBwAgACABags='));)json"
    R"json(if(!(r.module instanceof WebAssembly.Module)||!(r.instance instanceof WebAssembly.Instance))throw new Error('wasm instantiateStreaming did not return module and instance');)json"
    R"json(if(r.instance.exports.add(20,22)!==42)throw new Error('wasm instantiateStreaming add result was not 42');)json"
    R"json(console.log('chromium-wasm-m8-page-webassembly-instantiate-streaming-data-url-add-42');)json"
    R"json(return 'wasm-instantiate-streaming-data-url-add-42';})()","returnByValue":true,)json"
    R"json("awaitPromise":true,"allowUnsafeEvalBlockedByCSP":false}})json";
constexpr char kFixedDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20DevTools%20smoke";
constexpr char kFixedPageWebAssemblyDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20smoke";
constexpr char kFixedPageWebAssemblyMemoryDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20memory%20smoke";
constexpr char kFixedPageWebAssemblyTableDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20table%20smoke";
constexpr char kFixedPageWebAssemblyTableGrowthDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20table%20growth%20smoke";
constexpr char kFixedPageWebAssemblyMemoryGrowthDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20memory%20growth%20smoke";
constexpr char kFixedPageWebAssemblyExceptionDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20exception%20smoke";
constexpr char kFixedPageWebAssemblyWasmMemoryGrowOpcodeDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20Wasm%20memory%20grow%20opcode%20smoke";
constexpr char kFixedPageWebAssemblyWasmTableGrowOpcodeDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20Wasm%20table%20grow%20opcode%20smoke";
constexpr char kFixedPageWebAssemblyWasmThrowDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20Wasm%20throw%20smoke";
constexpr char kFixedPageWebAssemblyWasmThrowPayloadDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20Wasm%20throw%20payload%20smoke";
constexpr char kFixedPageWebAssemblyJsThrowPayloadDevToolsProtocolSmokeUrl[] =
    "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20JavaScript%20throw%20payload%20smoke";
constexpr char
    kFixedPageWebAssemblyInstantiateStreamingDevToolsProtocolSmokeUrl[] =
        "data:text/html;charset=utf-8,Chromium%20Wasm%20page%20WebAssembly%20instantiateStreaming%20smoke";
constexpr char kNetworkEnableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:NETWORK_ENABLE_OK";
constexpr char kRuntimeEnableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_ENABLE_OK";
constexpr char kRuntimeEvaluateSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_EVALUATE_OK";
constexpr char kPageWebAssemblyUnavailableSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:PAGE_WEBASSEMBLY_UNAVAILABLE";
constexpr char kPageWebAssemblySuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:VALIDATED_MODULE_CONSTRUCTED_INSTANCE_ADD_42_OK";
constexpr char kPageWebAssemblyMemorySuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK";
constexpr char kPageWebAssemblyTableSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_ELEMENT_INITIALIZED_INDIRECT_CALL_42_OK";
constexpr char kPageWebAssemblyTableGrowthSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_ENTRIES_INITIALIZED_INDIRECT_CALL_42_OK";
constexpr char kPageWebAssemblyMemoryGrowthSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_GROWN_1_TO_2_PAGES_POST_GROWTH_JS_WRITE_WASM_READ_WASM_WRITE_JS_READ_OK";
constexpr char kPageWebAssemblyExceptionSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_CONSTRUCTED_IMPORTED_TAG_JS_THROW_WASM_CATCH_42_OK";
constexpr char kPageWebAssemblyWasmMemoryGrowOpcodeSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "MEMORY_CONSTRUCTED_IMPORTED_WASM_MEMORY_GROW_OPCODE_GROWN_1_TO_2_PAGES_BUFFER_REPLACED_OK";
constexpr char kPageWebAssemblyWasmTableGrowOpcodeSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "TABLE_CONSTRUCTED_IMPORTED_WASM_TABLE_GROW_OPCODE_GROWN_1_TO_2_ENTRIES_INITIALIZED_INDIRECT_CALL_42_OK";
constexpr char kPageWebAssemblyWasmThrowSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_TAG_WASM_THROW_JS_CATCH_OK";
constexpr char kPageWebAssemblyWasmThrowPayloadSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_I32_TAG_WASM_THROW_JS_CATCH_PAYLOAD_42_OK";
constexpr char kPageWebAssemblyJsThrowPayloadSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "EXCEPTION_IMPORTED_I32_TAG_JS_THROW_WASM_CATCH_PAYLOAD_42_OK";
constexpr char kPageWebAssemblyInstantiateStreamingSuccessMarker[] =
    "CHROMIUM_WASM_M8_PAGE_WEBASSEMBLY:"
    "INSTANTIATE_STREAMING_DATA_URL_APPLICATION_WASM_MODULE_INSTANCE_ADD_42_OK";
constexpr char kRuntimeConsoleApiCalledSuccessMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:RUNTIME_CONSOLE_API_CALLED_OK";
constexpr char kDetachedMarker[] =
    "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:DETACHED";
constexpr char kFailureMarker[] = "CHROMIUM_WASM_M8_DEVTOOLS_PROTOCOL:FAIL";
constexpr int kNetworkEnableCommandId = 1;
constexpr int kRuntimeEnableCommandId = 2;
constexpr int kRuntimeEvaluateCommandId = 3;
constexpr size_t kMaximumProtocolResponseBytes = 4 * 1024;
constexpr char kRuntimeEvaluateExpectedType[] = "string";
constexpr char kRuntimeEvaluateExpectedValue[] = "undefined";
constexpr char kPageWebAssemblyRuntimeEvaluateExpectedValue[] =
    "wasm-add-42";
constexpr char kPageWebAssemblyMemoryRuntimeEvaluateExpectedValue[] =
    "wasm-memory-import-read-write";
constexpr char kPageWebAssemblyTableRuntimeEvaluateExpectedValue[] =
    "wasm-table-import-indirect-call";
constexpr char kPageWebAssemblyTableGrowthRuntimeEvaluateExpectedValue[] =
    "wasm-table-growth-import-grown-indirect-call";
constexpr char kPageWebAssemblyMemoryGrowthRuntimeEvaluateExpectedValue[] =
    "wasm-memory-growth-import-post-growth-read-write";
constexpr char kPageWebAssemblyExceptionRuntimeEvaluateExpectedValue[] =
    "wasm-exception-imported-tag-js-throw-wasm-catch";
constexpr char kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateExpectedValue[] =
    "wasm-memory-grow-opcode-import-one-to-two-pages";
constexpr char kPageWebAssemblyWasmTableGrowOpcodeRuntimeEvaluateExpectedValue[] =
    "wasm-table-grow-opcode-import-one-to-two-entries-indirect-call";
constexpr char kPageWebAssemblyWasmThrowRuntimeEvaluateExpectedValue[] =
    "wasm-throw-imported-tag-js-catch";
constexpr char kPageWebAssemblyWasmThrowPayloadRuntimeEvaluateExpectedValue[] =
    "wasm-throw-imported-i32-tag-js-catch-payload-42";
constexpr char kPageWebAssemblyJsThrowPayloadRuntimeEvaluateExpectedValue[] =
    "wasm-exception-imported-i32-tag-js-throw-wasm-catch-payload-42";
constexpr char kPageWebAssemblyInstantiateStreamingRuntimeEvaluateExpectedValue[] =
    "wasm-instantiate-streaming-data-url-add-42";
constexpr char kRuntimeConsoleApiCalledMethod[] = "Runtime.consoleAPICalled";
constexpr char kRuntimeConsoleApiCalledExpectedType[] = "log";
constexpr char kRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-devtools-console";
constexpr char kPageWebAssemblyRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-add-42";
constexpr char kPageWebAssemblyMemoryRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-memory-import-read-write";
constexpr char kPageWebAssemblyTableRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-table-import-indirect-call";
constexpr char
    kPageWebAssemblyTableGrowthRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-table-growth-import-grown-"
        "indirect-call";
constexpr char
    kPageWebAssemblyMemoryGrowthRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-memory-growth-import-post-growth-"
        "read-write";
constexpr char kPageWebAssemblyExceptionRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-exception-imported-tag-js-throw-wasm-"
    "catch";
constexpr char
    kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-wasm-memory-grow-opcode-import-"
        "one-to-two-pages";
constexpr char
    kPageWebAssemblyWasmTableGrowOpcodeRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-wasm-table-grow-opcode-import-"
        "one-to-two-entries-indirect-call";
constexpr char kPageWebAssemblyWasmThrowRuntimeConsoleApiCalledExpectedValue[] =
    "chromium-wasm-m8-page-webassembly-wasm-throw-imported-tag-js-catch";
constexpr char
    kPageWebAssemblyWasmThrowPayloadRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-wasm-throw-imported-i32-tag-js-"
        "catch-payload-42";
constexpr char
    kPageWebAssemblyJsThrowPayloadRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-imported-i32-tag-js-throw-wasm-"
        "catch-payload-42";
constexpr char
    kPageWebAssemblyInstantiateStreamingRuntimeConsoleApiCalledExpectedValue[] =
        "chromium-wasm-m8-page-webassembly-instantiate-streaming-data-url-"
        "add-42";

}  // namespace

GURL GetWasmBrowserDevToolsProtocolSmokeUrl(
    WasmBrowserDevToolsProtocolSmokeMode mode) {
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    return GURL(kFixedDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42) {
    return GURL(kFixedPageWebAssemblyDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
    return GURL(kFixedPageWebAssemblyMemoryDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
    return GURL(kFixedPageWebAssemblyTableDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kTableGrowImportIndirectCall) {
    return GURL(kFixedPageWebAssemblyTableGrowthDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kMemoryGrowImportReadWrite) {
    return GURL(kFixedPageWebAssemblyMemoryGrowthDevToolsProtocolSmokeUrl);
  }
  if (mode == WasmBrowserDevToolsProtocolSmokeMode::
                   kExceptionImportedTagJsThrowWasmCatch) {
    return GURL(kFixedPageWebAssemblyExceptionDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kWasmMemoryGrowOpcodeImport) {
    return GURL(
        kFixedPageWebAssemblyWasmMemoryGrowOpcodeDevToolsProtocolSmokeUrl);
  }
  if (mode == WasmBrowserDevToolsProtocolSmokeMode::
                   kWasmTableGrowOpcodeImportIndirectCall) {
    return GURL(
        kFixedPageWebAssemblyWasmTableGrowOpcodeDevToolsProtocolSmokeUrl);
  }
  if (mode ==
      WasmBrowserDevToolsProtocolSmokeMode::kWasmThrowImportedTagJsCatch) {
    return GURL(kFixedPageWebAssemblyWasmThrowDevToolsProtocolSmokeUrl);
  }
  if (mode == WasmBrowserDevToolsProtocolSmokeMode::
                  kWasmThrowImportedI32TagJsCatchPayload) {
    return GURL(kFixedPageWebAssemblyWasmThrowPayloadDevToolsProtocolSmokeUrl);
  }
  if (mode == WasmBrowserDevToolsProtocolSmokeMode::
                  kExceptionImportedI32TagJsThrowWasmCatchPayload) {
    return GURL(kFixedPageWebAssemblyJsThrowPayloadDevToolsProtocolSmokeUrl);
  }
  CHECK_EQ(mode, WasmBrowserDevToolsProtocolSmokeMode::
                     kInstantiateStreamingDataUrlModuleAdd42);
  return GURL(kFixedPageWebAssemblyInstantiateStreamingDevToolsProtocolSmokeUrl);
}

WasmBrowserDevToolsProtocolSmoke::WasmBrowserDevToolsProtocolSmoke(
    base::OnceClosure success_callback)
    : WasmBrowserDevToolsProtocolSmoke(
          WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable,
          std::move(success_callback)) {}

WasmBrowserDevToolsProtocolSmoke::WasmBrowserDevToolsProtocolSmoke(
    WasmBrowserDevToolsProtocolSmokeMode mode,
    base::OnceClosure success_callback)
    : mode_(mode), success_callback_(std::move(success_callback)) {
  CHECK(success_callback_);
}

WasmBrowserDevToolsProtocolSmoke::~WasmBrowserDevToolsProtocolSmoke() {
  Detach();
}

void WasmBrowserDevToolsProtocolSmoke::Start(
    content::WebContents* web_contents) {
  CHECK_CURRENTLY_ON(content::BrowserThread::UI);
  CHECK(web_contents);
  CHECK_EQ(state_, State::kCreated);
  CHECK(!agent_host_);
  CHECK(!primary_main_frame_);
  CHECK(!permitted_url_.is_valid());

  const GURL expected_url(GetWasmBrowserDevToolsProtocolSmokeUrl(mode_));
  CHECK(expected_url.is_valid());
  CHECK_EQ(web_contents->GetLastCommittedURL(), expected_url);

  primary_main_frame_ = web_contents->GetPrimaryMainFrame();
  CHECK(primary_main_frame_);
  CHECK_EQ(primary_main_frame_->GetLastCommittedURL(), expected_url);
  permitted_url_ = expected_url;

  agent_host_ = content::DevToolsAgentHost::GetOrCreateFor(web_contents);
  if (!agent_host_) {
    Fail("could not create the active tab's DevTools agent host");
  }
  if (!agent_host_->AttachClient(this)) {
    agent_host_ = nullptr;
    Fail("could not attach the fixed protocol client");
  }

  state_ = State::kEnablingNetwork;
  // These three literal commands are the only protocol messages this client
  // can emit. There is no frontend, pipe, socket, host ABI, or caller-provided
  // command surface. The default Runtime.evaluate expression reads only
  // |typeof WebAssembly| to make the current disabled page-WebAssembly
  // boundary observable; it neither constructs nor compiles a page module and
  // does not enable page WebAssembly. The closed alternate expressions use
  // only literal module bytes and fixed add, memory import/read-write, table
  // import/indirect-call, table-growth, memory-growth, exception, or
  // memory.grow-opcode, table.grow-opcode, zero-payload Wasm-throw, or typed
  // Wasm-throw-payload witnesses.
  agent_host_->DispatchProtocolMessage(
      this, base::byte_span_from_cstring(kNetworkEnableCommand));
}

bool WasmBrowserDevToolsProtocolSmoke::IsDetached() const {
  return state_ == State::kDetached && !agent_host_;
}

void WasmBrowserDevToolsProtocolSmoke::DispatchProtocolMessage(
    content::DevToolsAgentHost* agent_host,
    base::span<const uint8_t> message) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if ((state_ != State::kEnablingNetwork &&
       state_ != State::kEnablingRuntime &&
       state_ != State::kEvaluatingRuntime) ||
      agent_host != agent_host_.get()) {
    return;
  }
  if (message.size() > kMaximumProtocolResponseBytes) {
    Fail("fixed DevTools protocol response exceeded its bound");
  }

  const std::string_view message_text(
      reinterpret_cast<const char*>(message.data()), message.size());
  std::optional<base::Value> value =
      base::JSONReader::Read(message_text, base::JSON_PARSE_RFC);
  if (!value || !value->is_dict()) {
    // Ignore malformed or unrelated protocol frames; this smoke is not a
    // generic protocol consumer.
    return;
  }

  const base::DictValue& response = value->GetDict();
  const std::string* method = response.FindString("method");
  if (method) {
    if (*method == kRuntimeConsoleApiCalledMethod &&
        state_ == State::kEvaluatingRuntime) {
      CompleteRuntimeConsoleApiCalled(response);
    }
    return;
  }
  const std::optional<int> id = response.FindInt("id");
  if (!id) {
    return;
  }

  if (state_ == State::kEnablingNetwork) {
    if (*id != kNetworkEnableCommandId) {
      return;
    }
    const base::DictValue* result = response.FindDict("result");
    if (response.Find("error") || !result || !result->empty()) {
      Fail("Network.enable did not return its fixed empty result");
    }
    CompleteNetworkEnable();
    return;
  }

  if (state_ == State::kEnablingRuntime) {
    if (*id != kRuntimeEnableCommandId) {
      return;
    }
    const base::DictValue* result = response.FindDict("result");
    if (response.Find("error") || !result || !result->empty()) {
      Fail("Runtime.enable did not return its fixed empty result");
    }
    CompleteRuntimeEnable();
    return;
  }

  CHECK_EQ(state_, State::kEvaluatingRuntime);
  if (*id != kRuntimeEvaluateCommandId) {
    return;
  }
  const base::DictValue* result = response.FindDict("result");
  if (response.Find("error") || !result || result->Find("exceptionDetails")) {
    Fail("Runtime.evaluate did not return a fixed ordinary-JavaScript result");
  }
  const base::DictValue* remote_result = result->FindDict("result");
  const std::string* result_type =
      remote_result ? remote_result->FindString("type") : nullptr;
  const std::string* result_value =
      remote_result ? remote_result->FindString("value") : nullptr;
  const char* expected_value = nullptr;
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    expected_value = kRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    expected_value = kPageWebAssemblyRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
    expected_value = kPageWebAssemblyMemoryRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
    expected_value = kPageWebAssemblyTableRuntimeEvaluateExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kTableGrowImportIndirectCall) {
    expected_value = kPageWebAssemblyTableGrowthRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryGrowImportReadWrite) {
    expected_value = kPageWebAssemblyMemoryGrowthRuntimeEvaluateExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedTagJsThrowWasmCatch) {
    expected_value = kPageWebAssemblyExceptionRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmMemoryGrowOpcodeImport) {
    expected_value =
        kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmTableGrowOpcodeImportIndirectCall) {
    expected_value =
        kPageWebAssemblyWasmTableGrowOpcodeRuntimeEvaluateExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmThrowImportedTagJsCatch) {
    expected_value =
        kPageWebAssemblyWasmThrowRuntimeEvaluateExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmThrowImportedI32TagJsCatchPayload) {
    expected_value =
        kPageWebAssemblyWasmThrowPayloadRuntimeEvaluateExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedI32TagJsThrowWasmCatchPayload) {
    expected_value =
        kPageWebAssemblyJsThrowPayloadRuntimeEvaluateExpectedValue;
  } else {
    CHECK_EQ(mode_, WasmBrowserDevToolsProtocolSmokeMode::
                        kInstantiateStreamingDataUrlModuleAdd42);
    expected_value =
        kPageWebAssemblyInstantiateStreamingRuntimeEvaluateExpectedValue;
  }
  if (!result_type || *result_type != kRuntimeEvaluateExpectedType ||
      !result_value || *result_value != expected_value) {
    if (mode_ ==
        WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
      Fail("Runtime.evaluate did not return the fixed "
           "page-WebAssembly-unavailable result");
    }
    if (mode_ ==
        WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "memory import/read-write result");
    }
    if (mode_ ==
        WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "table import/indirect-call result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kTableGrowImportIndirectCall) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "table growth import/indirect-call result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kMemoryGrowImportReadWrite) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "memory growth import/post-growth read-write result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kExceptionImportedTagJsThrowWasmCatch) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "exception imported-tag JS-throw/Wasm-catch result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kWasmMemoryGrowOpcodeImport) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "Wasm memory.grow opcode import one-to-two-pages result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kWasmTableGrowOpcodeImportIndirectCall) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "Wasm table.grow opcode import one-to-two-entries indirect-call "
           "result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kWasmThrowImportedTagJsCatch) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "Wasm-throw imported-tag JavaScript-catch result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kWasmThrowImportedI32TagJsCatchPayload) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "Wasm-throw imported-i32-tag JavaScript-catch-payload-42 result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kExceptionImportedI32TagJsThrowWasmCatchPayload) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "JavaScript-throw imported-i32-tag Wasm-catch-payload-42 result");
    }
    if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                     kInstantiateStreamingDataUrlModuleAdd42) {
      Fail("Runtime.evaluate did not return the fixed page-WebAssembly "
           "instantiateStreaming data:application/wasm add(20, 22) result");
    }
    Fail("Runtime.evaluate did not return the fixed "
         "page-WebAssembly add(20, 22) result");
  }
  if (runtime_evaluate_response_received_) {
    Fail("Runtime.evaluate returned more than one fixed response");
  }
  runtime_evaluate_response_received_ = true;
  std::fprintf(stderr, "%s\n", kRuntimeEvaluateSuccessMarker);
  std::fflush(stderr);
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyUnavailableSuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblySuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyMemorySuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyTableSuccessMarker);
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kTableGrowImportIndirectCall) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyTableGrowthSuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryGrowImportReadWrite) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyMemoryGrowthSuccessMarker);
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedTagJsThrowWasmCatch) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyExceptionSuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmMemoryGrowOpcodeImport) {
    std::fprintf(stderr, "%s\n",
                 kPageWebAssemblyWasmMemoryGrowOpcodeSuccessMarker);
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmTableGrowOpcodeImportIndirectCall) {
    std::fprintf(stderr, "%s\n",
                 kPageWebAssemblyWasmTableGrowOpcodeSuccessMarker);
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmThrowImportedTagJsCatch) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyWasmThrowSuccessMarker);
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmThrowImportedI32TagJsCatchPayload) {
    std::fprintf(stderr, "%s\n",
                 kPageWebAssemblyWasmThrowPayloadSuccessMarker);
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedI32TagJsThrowWasmCatchPayload) {
    std::fprintf(stderr, "%s\n", kPageWebAssemblyJsThrowPayloadSuccessMarker);
  } else {
    CHECK_EQ(mode_, WasmBrowserDevToolsProtocolSmokeMode::
                        kInstantiateStreamingDataUrlModuleAdd42);
    std::fprintf(stderr, "%s\n",
                 kPageWebAssemblyInstantiateStreamingSuccessMarker);
  }
  std::fflush(stderr);
  CompleteRuntimeEvaluate();
}

void WasmBrowserDevToolsProtocolSmoke::AgentHostClosed(
    content::DevToolsAgentHost* agent_host) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (agent_host != agent_host_.get()) {
    return;
  }
  agent_host_ = nullptr;
  if (state_ != State::kDetached) {
    Fail("active tab DevTools agent host closed before detaching");
  }
}

bool WasmBrowserDevToolsProtocolSmoke::MayAttachToURL(const GURL& url,
                                                      bool is_webui) {
  // This client is authorized only for the fixed, lifecycle-owned primary
  // document selected at Start(). Attachment is separately constrained to
  // |primary_main_frame_|. Any navigation request therefore forces a detach
  // rather than widening this test-only authority.
  return !is_webui && permitted_url_.is_valid() && url == permitted_url_;
}

bool WasmBrowserDevToolsProtocolSmoke::MayAttachToRenderFrameHost(
    content::RenderFrameHost* render_frame_host) {
  return render_frame_host == primary_main_frame_;
}

bool WasmBrowserDevToolsProtocolSmoke::IsTrusted() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayAccessAllCookies() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayReadLocalFiles() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::MayWriteLocalFiles() {
  return false;
}

bool WasmBrowserDevToolsProtocolSmoke::AllowUnsafeOperations() {
  return false;
}

void WasmBrowserDevToolsProtocolSmoke::CompleteNetworkEnable() {
  CHECK_EQ(state_, State::kEnablingNetwork);
  CHECK(agent_host_);

  // Advance before dispatch because a DevTools agent may synchronously deliver
  // the fixed Runtime.enable response while handling this call.
  state_ = State::kEnablingRuntime;
  std::fprintf(stderr, "%s\n", kNetworkEnableSuccessMarker);
  std::fflush(stderr);
  agent_host_->DispatchProtocolMessage(
      this, base::byte_span_from_cstring(kRuntimeEnableCommand));
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeEnable() {
  CHECK_EQ(state_, State::kEnablingRuntime);
  CHECK(agent_host_);

  // Runtime.enable must complete before the one expression can generate the
  // exact console event. Set the state before dispatch because either the
  // notification or the response can be delivered synchronously, in either
  // order, while this call is active.
  state_ = State::kEvaluatingRuntime;
  std::fprintf(stderr, "%s\n", kRuntimeEnableSuccessMarker);
  std::fflush(stderr);
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    agent_host_->DispatchProtocolMessage(
        this, base::byte_span_from_cstring(kRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kValidateModuleInstanceAdd42) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(kPageWebAssemblyRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyMemoryRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyTableRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kTableGrowImportIndirectCall) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyTableGrowthRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kMemoryGrowImportReadWrite) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyMemoryGrowthRuntimeEvaluateCommand));
    return;
  }
  if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                   kExceptionImportedTagJsThrowWasmCatch) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyExceptionRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kWasmMemoryGrowOpcodeImport) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeEvaluateCommand));
    return;
  }
  if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                   kWasmTableGrowOpcodeImportIndirectCall) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyWasmTableGrowOpcodeRuntimeEvaluateCommand));
    return;
  }
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kWasmThrowImportedTagJsCatch) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyWasmThrowRuntimeEvaluateCommand));
    return;
  }
  if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                  kWasmThrowImportedI32TagJsCatchPayload) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyWasmThrowPayloadRuntimeEvaluateCommand));
    return;
  }
  if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                   kExceptionImportedI32TagJsThrowWasmCatchPayload) {
    agent_host_->DispatchProtocolMessage(
        this,
        base::byte_span_from_cstring(
            kPageWebAssemblyJsThrowPayloadRuntimeEvaluateCommand));
    return;
  }
  CHECK_EQ(mode_, WasmBrowserDevToolsProtocolSmokeMode::
                      kInstantiateStreamingDataUrlModuleAdd42);
  agent_host_->DispatchProtocolMessage(
      this,
      base::byte_span_from_cstring(
          kPageWebAssemblyInstantiateStreamingRuntimeEvaluateCommand));
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeConsoleApiCalled(
    const base::DictValue& notification) {
  CHECK_EQ(state_, State::kEvaluatingRuntime);
  const base::DictValue* params = notification.FindDict("params");
  const std::string* type = params ? params->FindString("type") : nullptr;
  const base::ListValue* arguments =
      params ? params->FindList("args") : nullptr;
  const base::DictValue* argument =
      arguments && arguments->size() == 1 ? (*arguments)[0].GetIfDict()
                                          : nullptr;
  const std::string* argument_type =
      argument ? argument->FindString("type") : nullptr;
  const std::string* argument_value =
      argument ? argument->FindString("value") : nullptr;
  const char* expected_value = nullptr;
  if (mode_ ==
      WasmBrowserDevToolsProtocolSmokeMode::kPageWebAssemblyUnavailable) {
    expected_value = kRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::
                 kValidateModuleInstanceAdd42) {
    expected_value = kPageWebAssemblyRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryImportReadWrite) {
    expected_value =
        kPageWebAssemblyMemoryRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kTableImportIndirectCall) {
    expected_value = kPageWebAssemblyTableRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kTableGrowImportIndirectCall) {
    expected_value =
        kPageWebAssemblyTableGrowthRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kMemoryGrowImportReadWrite) {
    expected_value =
        kPageWebAssemblyMemoryGrowthRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedTagJsThrowWasmCatch) {
    expected_value =
        kPageWebAssemblyExceptionRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmMemoryGrowOpcodeImport) {
    expected_value =
        kPageWebAssemblyWasmMemoryGrowOpcodeRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmTableGrowOpcodeImportIndirectCall) {
    expected_value =
        kPageWebAssemblyWasmTableGrowOpcodeRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ ==
             WasmBrowserDevToolsProtocolSmokeMode::kWasmThrowImportedTagJsCatch) {
    expected_value =
        kPageWebAssemblyWasmThrowRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kWasmThrowImportedI32TagJsCatchPayload) {
    expected_value =
        kPageWebAssemblyWasmThrowPayloadRuntimeConsoleApiCalledExpectedValue;
  } else if (mode_ == WasmBrowserDevToolsProtocolSmokeMode::
                          kExceptionImportedI32TagJsThrowWasmCatchPayload) {
    expected_value =
        kPageWebAssemblyJsThrowPayloadRuntimeConsoleApiCalledExpectedValue;
  } else {
    CHECK_EQ(mode_, WasmBrowserDevToolsProtocolSmokeMode::
                        kInstantiateStreamingDataUrlModuleAdd42);
    expected_value =
        kPageWebAssemblyInstantiateStreamingRuntimeConsoleApiCalledExpectedValue;
  }
  if (!type || *type != kRuntimeConsoleApiCalledExpectedType ||
      !argument_type ||
      *argument_type != kRuntimeEvaluateExpectedType || !argument_value ||
      *argument_value != expected_value) {
    Fail("Runtime.consoleAPICalled did not contain the fixed log argument");
  }
  if (runtime_console_api_called_received_) {
    Fail("Runtime.consoleAPICalled was delivered more than once");
  }
  runtime_console_api_called_received_ = true;
  std::fprintf(stderr, "%s\n", kRuntimeConsoleApiCalledSuccessMarker);
  std::fflush(stderr);
  CompleteRuntimeEvaluate();
}

void WasmBrowserDevToolsProtocolSmoke::CompleteRuntimeEvaluate() {
  CHECK_EQ(state_, State::kEvaluatingRuntime);
  if (!runtime_evaluate_response_received_ ||
      !runtime_console_api_called_received_) {
    return;
  }
  CHECK(success_callback_);

  // Keep both the fixed result and exact console-event witnesses before
  // detachment, then make detachment an independently observable barrier
  // before the lifecycle is allowed to close its Browser and destroy the sole
  // WebContents.
  Detach();
  state_ = State::kDetached;
  CHECK(IsDetached());
  std::fprintf(stderr, "%s\n", kDetachedMarker);
  std::fflush(stderr);

  // The lifecycle owns this object until its Browser close observer clears
  // it, so running this callback cannot destroy |this| while this method is
  // still active.
  std::move(success_callback_).Run();
}

[[noreturn]] void WasmBrowserDevToolsProtocolSmoke::Fail(
    std::string_view reason) {
  state_ = State::kFailed;
  Detach();
  std::fprintf(stderr, "%s reason=%.*s\n", kFailureMarker,
               static_cast<int>(reason.size()), reason.data());
  std::fflush(stderr);
  CHECK(false) << "Wasm DevTools protocol smoke failed: " << reason;
}

void WasmBrowserDevToolsProtocolSmoke::Detach() {
  if (!agent_host_) {
    return;
  }
  scoped_refptr<content::DevToolsAgentHost> agent_host =
      std::move(agent_host_);
  CHECK(agent_host->DetachClient(this));
}

}  // namespace chrome
