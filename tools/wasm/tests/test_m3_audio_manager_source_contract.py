#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import unittest

from tools.wasm.tests.m3_source_contract_test_support import source


class M3AudioManagerSourceContractTest(unittest.TestCase):
    def test_wasm_selects_dedicated_audio_manager_and_test(self) -> None:
        build = source("media/audio/BUILD.gn")
        wasm_audio = build.split('source_set("audio")', 1)[1].split(
            "  if (!is_wasm)", 1
        )[0]
        wasm_tests = build.split(
            'if (is_wasm) {\n'
            '    sources += [ "audio_manager_wasm_unittest.cc" ]',
            1,
        )[1].split("  configs +=", 1)[0]

        self.assertIn('if (is_wasm) {', wasm_audio)
        self.assertIn('"audio_manager_wasm.cc"', wasm_audio)
        self.assertIn('"audio_output_stream_wasm.cc"', wasm_audio)
        self.assertIn('"wasm_audio_bridge.cc"', wasm_audio)
        self.assertIn('inputs = [ "wasm_audio_bridge.js" ]', wasm_audio)
        self.assertIn('all_dependent_configs = [ ":wasm_audio_bridge" ]', wasm_audio)
        self.assertIn("if (!is_wasm)", wasm_tests)
        self.assertNotIn("audio_manager_linux.cc", wasm_audio)
        self.assertIn('executable("wasm_audio_manager_output_smoke")', build)

    def test_wasm_requires_an_armed_host_for_one_real_output_stream(self) -> None:
        implementation = source("media/audio/audio_manager_wasm.cc")

        self.assertIn(
            "class AudioManagerWasm final : public AudioManagerBase",
            implementation,
        )
        self.assertIn(
            "SetMaxOutputStreamsAllowed(1);",
            implementation,
        )
        self.assertIn("!wasm_audio::IsOutputArmed()", implementation)
        self.assertIn("IsSupportedOutputParameters(params)", implementation)
        self.assertIn("AudioManagerBase::MakeAudioOutputStream", implementation)
        self.assertIn("AUDIO_FAKE", implementation)
        self.assertIn("MakeAudioOutputStreamProxy", implementation)
        self.assertIn("MakeAudioInputStream", implementation)
        self.assertIn("MakeLinearInputStream", implementation)
        self.assertIn("MakeLowLatencyInputStream", implementation)
        self.assertIn(
            "bool HasAudioInputDevices() override {\n"
            "    CHECK(GetTaskRunner()->BelongsToCurrentThread());\n"
            "    return false;\n"
            "  }",
            implementation,
        )
        self.assertNotIn("FakeAudioManager", implementation)

    def test_wasm_audio_bridge_has_only_lifecycle_imports(self) -> None:
        bridge = source("media/audio/wasm_audio_bridge.js")
        stream = source("media/audio/audio_output_stream_wasm.cc")
        smoke = source("media/audio/wasm_audio_manager_output_smoke.cc")

        self.assertIn("__chromiumWasmAudioHostV1", bridge)
        self.assertIn("chromium_wasm_audio_output_is_armed__proxy: 'sync'", bridge)
        self.assertIn("chromium_wasm_audio_output_register__proxy: 'sync'", bridge)
        self.assertIn("chromium_wasm_audio_output_unregister__proxy: 'sync'", bridge)
        self.assertNotIn("AudioContext", bridge)
        self.assertNotIn("AudioWorklet", bridge)
        self.assertIn("emscripten_get_heap_size() != initial_heap_size_", stream)
        self.assertIn("wasm_audio::RegisterOutputRing", stream)
        self.assertIn("wasm_audio::UnregisterOutputRing", stream)
        self.assertIn("IsHostStartedForTesting", stream)
        self.assertIn("IsHostDrainedForTesting", stream)
        self.assertIn("pending_error_callback_", stream)
        stop = stream.split("void AudioOutputStreamWasm::Stop()", 1)[1].split(
            "void AudioOutputStreamWasm::SetVolume", 1
        )[0]
        self.assertIn("pending_error_callback_ = nullptr;", stop)
        report_error = stream.split("void AudioOutputStreamWasm::ReportError()", 1)[1].split(
            "void AudioOutputStreamWasm::FinishErrorOnAudioSequence()", 1
        )[0]
        finish_error = stream.split(
            "void AudioOutputStreamWasm::FinishErrorOnAudioSequence()", 1
        )[1].split("void AudioOutputStreamWasm::InitializeHeader()", 1)[0]
        self.assertNotIn("callback->OnError", report_error)
        self.assertIn("audio_worker_->Stop();", finish_error)
        self.assertIn("UnregisterRing();", finish_error)
        self.assertIn("callback->OnError", finish_error)
        register = bridge.split("chromium_wasm_audio_output_register: (", 1)[1].split(
            "chromium_wasm_audio_output_unregister__deps", 1
        )[0]
        self.assertNotIn("bridge.isOutputArmed() !== true", register)
        self.assertIn("EmitMarker(\"READY\")", smoke)
        self.assertIn("base::AtExitManager at_exit_manager;", smoke)
        self.assertIn("base::SingleThreadTaskExecutor application_executor", smoke)
        self.assertIn("std::unique_ptr<ThreadPoolForSmoke> thread_pool", smoke)
        self.assertIn(
            "base::ThreadPoolInstance::CreateAndStartWithDefaultParams(", smoke
        )
        self.assertIn("thread_pool->Shutdown();", smoke)
        self.assertIn("ShutdownAudioManagerForSmoke", smoke)
        self.assertIn("TerminalAudioTombstone", smoke)
        self.assertIn("std::move(*thread_pool), std::move(*log_factory)", smoke)
        self.assertIn("std::move(*manager),", smoke)
        self.assertIn("base::MakeRefCounted<OperationCompletion>()", smoke)
        self.assertNotIn("&completed", smoke)
        self.assertIn("kCompletedFailure", smoke)
        self.assertIn("kPostRejected", smoke)
        self.assertIn("RequiresTerminalTombstone", smoke)
        self.assertIn("PostOpen(manager.get(), state)", smoke)
        self.assertIn("PostStopAndClose(manager.get(), state);", smoke)
        self.assertIn("EmitMarker(\"OPENED\")", smoke)
        self.assertIn("WaitForHostStart(state->wasm_stream)", smoke)
        self.assertIn("PostStart(manager.get(), source, state)", smoke)
        self.assertIn("stream->IsHostDrainedForTesting()", smoke)
        self.assertIn("EmitMarker(\"STARTED\")", smoke)

    def test_wasm_sync_socket_cannot_back_audio_data_pipes(self) -> None:
        implementation = source("base/sync_socket_wasm.cc")
        create_pair = implementation.split(
            "bool SyncSocket::CreatePair(", 1
        )[1].split("\n}", 1)[0]

        self.assertIn(
            "Cross-process synchronization sockets have no role", create_pair
        )
        self.assertIn("return false;", create_pair)

    def test_wasm_audio_streams_reject_native_handle_transfer(self) -> None:
        input_stream = source("services/audio/input_stream.cc")
        output_stream = source("services/audio/output_stream.cc")
        loopback_stream = source("services/audio/loopback_stream.cc")

        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  // Audio data pipes require a transferable native sync-socket "
            "handle.",
            input_stream,
        )
        self.assertIn(
            "  OnStreamPlatformError();\n"
            "  return;\n"
            "#else\n"
            "  const base::TimeTicks start_time",
            input_stream,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "  // Wasm has no transferable native sync-socket handle.",
            output_stream,
        )
        self.assertIn(
            "  std::move(created_callback).Run(nullptr);\n"
            "  OnError();\n"
            "  return;\n"
            "#else\n"
            "  const base::TimeTicks start_time",
            output_stream,
        )
        self.assertIn(
            "#if BUILDFLAG(IS_WASM)\n"
            "    // Audio data pipes require a transferable native "
            "sync-socket handle.",
            loopback_stream,
        )
        self.assertIn(
            "    std::move(created_callback).Run(nullptr);\n"
            "    OnError();\n"
            "    return;\n"
            "#else\n",
            loopback_stream,
        )
        self.assertIn(
            "        writer->TakeSharedMemoryRegion();\n"
            "    mojo::PlatformHandle socket_handle;",
            loopback_stream,
        )


if __name__ == "__main__":
    unittest.main()
