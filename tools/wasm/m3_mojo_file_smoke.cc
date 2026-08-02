// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <errno.h>
#include <fcntl.h>
#include <unistd.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <utility>

#include "base/containers/span.h"
#include "base/files/file.h"
#include "build/build_config.h"
#include "mojo/core/embedder/embedder.h"
#include "mojo/public/cpp/bindings/message.h"
#include "mojo/public/cpp/system/message.h"
#include "mojo/public/cpp/system/message_pipe.h"
#include "mojo/public/mojom/base/file.mojom.h"

#if !BUILDFLAG(IS_WASM)
#error "m3_mojo_file_smoke must only be built for WebAssembly"
#endif

#if BUILDFLAG(IS_POSIX)
#error "WebAssembly must not inherit POSIX platform semantics"
#endif

namespace {

constexpr char kPrefix[] = "CHROMIUM_WASM_M3_MOJO_FILE";
constexpr std::string_view kFilePayload =
    "chromium-wasm-mojo-file-typemap";
constexpr std::string_view kReadOnlyPayload =
    "chromium-wasm-read-only-file-typemap";

int Fail(const char* reason) {
  std::fprintf(stderr, "%s:FAIL reason=%s\n", kPrefix, reason);
  std::fflush(stderr);
  return 1;
}

[[noreturn]] void FailImmediately(const char* reason) {
  Fail(reason);
  std::abort();
}

void Require(bool condition, const char* reason) {
  if (!condition) {
    FailImmediately(reason);
  }
}

void PrintPhase(const char* name) {
  std::fprintf(stdout, "%s:PHASE name=%s status=ok\n", kPrefix, name);
  std::fflush(stdout);
}

int CreatePopulatedFile(char* path_template, std::string_view payload) {
  const int descriptor = mkstemp(path_template);
  if (descriptor < 0) {
    return -1;
  }
  const ssize_t written = write(descriptor, payload.data(), payload.size());
  if (written != static_cast<ssize_t>(payload.size()) ||
      lseek(descriptor, 0, SEEK_SET) != 0) {
    close(descriptor);
    unlink(path_template);
    return -1;
  }
  return descriptor;
}

template <typename MojomType>
mojo::Message SerializeForTransport(base::File* sender) {
  mojo::Message message = MojomType::SerializeAsMessage(sender);
  Require(!message.IsNull(), "serialize_message_null");
  Require(!sender->IsValid(), "serialize_did_not_invalidate_sender");

  mojo::ScopedMessageHandle message_handle = message.TakeMojoMessage();
  Require(message_handle.is_valid(), "serialized_message_handle_invalid");
  mojo::MessagePipe pipe;
  Require(mojo::WriteMessageNew(pipe.handle0.get(), std::move(message_handle),
                                MOJO_WRITE_MESSAGE_FLAG_NONE) ==
              MOJO_RESULT_OK,
          "serialized_message_write_failed");
  mojo::ScopedMessageHandle received_message;
  Require(mojo::ReadMessageNew(pipe.handle1.get(), &received_message,
                               MOJO_READ_MESSAGE_FLAG_NONE) ==
                  MOJO_RESULT_OK &&
              received_message.is_valid(),
          "serialized_message_read_failed");
  message = mojo::Message::CreateFromMessageHandle(&received_message);
  Require(!message.IsNull() && !received_message.is_valid(),
          "serialized_message_transport_failed");
  return message;
}

void VerifyContent(base::File* file,
                   std::string_view expected,
                   const char* reason) {
  std::array<uint8_t, 64> bytes{};
  Require(expected.size() <= bytes.size(), "payload_exceeds_test_buffer");
  Require(file->ReadAndCheck(
              0, base::span(bytes).first(expected.size())) &&
              std::memcmp(bytes.data(), expected.data(), expected.size()) == 0,
          reason);
}

void VerifyClosedDescriptor(int descriptor, const char* reason) {
  uint8_t byte = 0;
  errno = 0;
  Require(read(descriptor, &byte, sizeof(byte)) == -1 && errno == EBADF,
          reason);
}

void TestFailedUnwrapClosesFile() {
  PrintPhase("file_failed_unwrap_closes");
  char path[] = "/tmp/chromium-wasm-mojo-failed-unwrap-XXXXXX";
  const int descriptor = CreatePopulatedFile(path, kFilePayload);
  Require(descriptor >= 0, "failed_unwrap_file_create");

  MojoPlatformHandle outbound_file{
      .struct_size = sizeof(outbound_file),
      .type = MOJO_PLATFORM_HANDLE_TYPE_FILE_DESCRIPTOR,
      .value = static_cast<uint64_t>(descriptor),
  };
  MojoHandle wrapped_file = MOJO_HANDLE_INVALID;
  Require(MojoWrapPlatformHandle(&outbound_file, nullptr, &wrapped_file) ==
                  MOJO_RESULT_OK &&
              wrapped_file != MOJO_HANDLE_INVALID,
          "failed_unwrap_file_wrap");

  MojoPlatformHandle invalid_output{
      .struct_size = 0,
      .type = MOJO_PLATFORM_HANDLE_TYPE_INVALID,
      .value = 0,
  };
  Require(MojoUnwrapPlatformHandle(wrapped_file, nullptr, &invalid_output) ==
              MOJO_RESULT_INVALID_ARGUMENT,
          "failed_unwrap_result");
  wrapped_file = MOJO_HANDLE_INVALID;
  VerifyClosedDescriptor(descriptor, "failed_unwrap_file_not_closed");
  Require(unlink(path) == 0, "failed_unwrap_file_cleanup");
}

void TestFileRoundTrip() {
  PrintPhase("file_round_trip");
  char path[] = "/tmp/chromium-wasm-mojo-file-XXXXXX";
  const int descriptor = CreatePopulatedFile(path, kFilePayload);
  Require(descriptor >= 0, "file_create");

  base::File sender(descriptor, /*async=*/true);
  Require(sender.IsValid() && sender.async(), "file_sender_invalid");
  mojo::Message message =
      SerializeForTransport<mojo_base::mojom::File>(&sender);

  base::File receiver;
  Require(mojo_base::mojom::File::DeserializeFromMessage(std::move(message),
                                                         &receiver),
          "file_deserialize");
  Require(receiver.IsValid() && receiver.GetPlatformFile() == descriptor,
          "file_receiver_ownership");
  Require(receiver.async(), "file_async_not_preserved");
  VerifyContent(&receiver, kFilePayload, "file_content_not_preserved");

  receiver.Close();
  VerifyClosedDescriptor(descriptor, "file_receiver_close_did_not_close");
  Require(unlink(path) == 0, "file_cleanup");
}

void TestReadOnlyFileRoundTrip() {
  PrintPhase("read_only_file_round_trip");
  char path[] = "/tmp/chromium-wasm-mojo-readonly-XXXXXX";
  int descriptor = CreatePopulatedFile(path, kReadOnlyPayload);
  Require(descriptor >= 0, "read_only_file_create");
  Require(close(descriptor) == 0, "read_only_file_writer_close");
  descriptor = open(path, O_RDONLY);
  Require(descriptor >= 0, "read_only_file_open");

  base::File sender(descriptor, /*async=*/false);
  Require(sender.IsValid() && !sender.async(), "read_only_sender_invalid");
  mojo::Message message =
      SerializeForTransport<mojo_base::mojom::ReadOnlyFile>(&sender);

  base::File receiver;
  Require(mojo_base::mojom::ReadOnlyFile::DeserializeFromMessage(
              std::move(message), &receiver),
          "read_only_file_deserialize");
  Require(receiver.IsValid() && receiver.GetPlatformFile() == descriptor,
          "read_only_file_receiver_ownership");
  Require(!receiver.async(), "read_only_file_async_not_preserved");
  VerifyContent(&receiver, kReadOnlyPayload,
                "read_only_file_content_not_preserved");

  receiver.Close();
  VerifyClosedDescriptor(descriptor,
                         "read_only_file_receiver_close_did_not_close");
  Require(unlink(path) == 0, "read_only_file_cleanup");
}

}  // namespace

int main() {
  std::fprintf(stdout, "%s:RUNTIME_START\n", kPrefix);
  std::fflush(stdout);

  mojo::core::Init(mojo::core::Configuration{.is_broker_process = true});
  TestFailedUnwrapClosesFile();
  TestFileRoundTrip();
  TestReadOnlyFileRoundTrip();
  mojo::core::ShutDown();

  std::fprintf(stdout, "%s:RUNTIME_END\n", kPrefix);
  std::fprintf(
      stdout,
      "%s:RESULT file_serialize=ok file_sender_invalidated=ok "
      "file_message_transport=ok file_deserialize=ok file_content=ok "
      "file_async_preserved=ok file_receiver_ownership=ok "
      "file_close_ebadf=ok read_only_serialize=ok "
      "file_failed_unwrap_closes=ok "
      "read_only_sender_invalidated=ok read_only_message_transport=ok "
      "read_only_deserialize=ok read_only_content=ok "
      "read_only_async_preserved=ok read_only_receiver_ownership=ok "
      "read_only_close_ebadf=ok clean_shutdown=ok\n",
      kPrefix);
  std::fprintf(stdout, "%s:PASS\n", kPrefix);
  std::fflush(stdout);
  return 0;
}
