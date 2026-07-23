// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "base/files/file_util.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cstring>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include "base/files/scoped_file.h"
#include "base/numerics/safe_conversions.h"
#include "base/posix/eintr_wrapper.h"
#include "build/build_config.h"

#if !BUILDFLAG(IS_WASM)
#error "file_util_wasm.cc must only be built for WebAssembly"
#endif

namespace base {
namespace {

// These operations target Emscripten's process-local MEMFS and execute on the
// Wasm application pthread. Scheduler blocking annotations are added with the
// M1.2 task runtime; they are intentionally not pulled into this M1.1 source
// slice.

bool DeletePath(const FilePath& path, bool recursive) {
  stat_wrapper_t info;
  if (File::Lstat(path, &info) != 0) {
    return errno == ENOENT;
  }

  if (!S_ISDIR(info.st_mode)) {
    return unlink(path.value().c_str()) == 0 || errno == ENOENT;
  }

  if (!recursive) {
    return rmdir(path.value().c_str()) == 0 || errno == ENOENT;
  }

  DIR* directory = opendir(path.value().c_str());
  if (!directory) {
    return false;
  }

  bool success = true;
  errno = 0;
  while (dirent* entry = readdir(directory)) {
    if (strcmp(entry->d_name, ".") == 0 ||
        strcmp(entry->d_name, "..") == 0) {
      continue;
    }
    if (!DeletePath(path.Append(entry->d_name), /*recursive=*/true)) {
      success = false;
      break;
    }
    errno = 0;
  }
  if (errno != 0) {
    success = false;
  }
  if (IGNORE_EINTR(closedir(directory)) != 0) {
    success = false;
  }
  if (!success) {
    return false;
  }
  return rmdir(path.value().c_str()) == 0 || errno == ENOENT;
}

FilePath TemporaryNameTemplate(const FilePath& directory,
                               FilePath::StringViewType prefix,
                               bool hidden) {
  std::string name = hidden ? "." : "";
  name.append("org.chromium.Chromium");
  if (!prefix.empty()) {
    name.push_back('.');
    name.append(prefix);
  }
  name.append(".XXXXXX");
  return directory.Append(name);
}

bool CopyRegularFile(const FilePath& from_path,
                     const FilePath& to_path,
                     bool open_exclusive) {
  ScopedFD input(
      HANDLE_EINTR(open(from_path.value().c_str(), O_RDONLY | O_NONBLOCK)));
  if (!input.is_valid()) {
    return false;
  }

  stat_wrapper_t info;
  if (File::Fstat(input.get(), &info) != 0 || !S_ISREG(info.st_mode)) {
    return false;
  }

  int flags = O_WRONLY | O_CREAT;
  flags |= open_exclusive ? O_EXCL : O_TRUNC;
  ScopedFD output(HANDLE_EINTR(
      open(to_path.value().c_str(), flags, S_IRUSR | S_IWUSR)));
  if (!output.is_valid()) {
    return false;
  }

  File input_file(std::move(input));
  File output_file(std::move(output));
  return CopyFileContents(input_file, output_file);
}

bool CopyDirectoryContents(const FilePath& from_path,
                           const FilePath& to_path,
                           bool recursive,
                           bool open_exclusive) {
  stat_wrapper_t source_info;
  if (File::Lstat(from_path, &source_info) != 0 ||
      !S_ISDIR(source_info.st_mode)) {
    return false;
  }

  const mode_t mode =
      (source_info.st_mode & 01777) | S_IRUSR | S_IWUSR | S_IXUSR;
  if (File::Mkdir(to_path, mode) != 0) {
    if (errno != EEXIST || open_exclusive || !DirectoryExists(to_path)) {
      return false;
    }
  }

  DIR* directory = opendir(from_path.value().c_str());
  if (!directory) {
    return false;
  }

  bool success = true;
  errno = 0;
  while (dirent* entry = readdir(directory)) {
    if (strcmp(entry->d_name, ".") == 0 ||
        strcmp(entry->d_name, "..") == 0) {
      continue;
    }

    const FilePath source = from_path.Append(entry->d_name);
    const FilePath destination = to_path.Append(entry->d_name);
    stat_wrapper_t entry_info;
    if (File::Lstat(source, &entry_info) != 0) {
      success = false;
      break;
    }

    if (S_ISDIR(entry_info.st_mode)) {
      if (recursive &&
          !CopyDirectoryContents(source, destination, /*recursive=*/true,
                                 open_exclusive)) {
        success = false;
        break;
      }
    } else if (S_ISREG(entry_info.st_mode) &&
               !CopyRegularFile(source, destination, open_exclusive)) {
      success = false;
      break;
    }
    errno = 0;
  }
  if (errno != 0) {
    success = false;
  }
  if (IGNORE_EINTR(closedir(directory)) != 0) {
    success = false;
  }
  return success;
}

bool CopyDirectoryImpl(const FilePath& from_path,
                       const FilePath& to_path,
                       bool recursive,
                       bool open_exclusive) {
  FilePath source = MakeAbsoluteFilePath(from_path);
  if (source.empty() || !DirectoryExists(source)) {
    return false;
  }

  FilePath destination = to_path;
  if (recursive && DirectoryExists(to_path)) {
    destination = to_path.Append(from_path.BaseName());
  }

  FilePath resolved_destination;
  if (PathExists(destination)) {
    resolved_destination = MakeAbsoluteFilePath(destination);
  } else {
    FilePath resolved_parent = MakeAbsoluteFilePath(destination.DirName());
    if (!resolved_parent.empty()) {
      resolved_destination = resolved_parent.Append(destination.BaseName());
    }
  }
  if (resolved_destination.empty() || resolved_destination == source ||
      source.IsParent(resolved_destination)) {
    return false;
  }

  return CopyDirectoryContents(source, destination, recursive, open_exclusive);
}

}  // namespace

bool CopyFileContents(File& input, File& output) {
  std::vector<uint8_t> buffer(32 * 1024);
  for (;;) {
    std::optional<size_t> bytes_read = input.ReadAtCurrentPos(buffer);
    if (!bytes_read.has_value()) {
      return false;
    }
    if (*bytes_read == 0) {
      return true;
    }

    span<const uint8_t> remaining = span(buffer).first(*bytes_read);
    while (!remaining.empty()) {
      std::optional<size_t> bytes_written =
          output.WriteAtCurrentPos(remaining);
      if (!bytes_written.has_value() || *bytes_written == 0) {
        return false;
      }
      remaining = remaining.subspan(*bytes_written);
    }
  }
}

FilePath MakeAbsoluteFilePath(const FilePath& input) {
  char resolved_path[PATH_MAX];
  if (!realpath(input.value().c_str(), resolved_path)) {
    return FilePath();
  }
  return FilePath(resolved_path);
}

std::optional<FilePath> MakeAbsoluteFilePathNoResolveSymbolicLinks(
    const FilePath& input) {
  if (input.empty()) {
    return std::nullopt;
  }

  FilePath collapsed_path;
  std::vector<FilePath::StringType> components = input.GetComponents();
  size_t first_component = 0;
  if (input.IsAbsolute()) {
    collapsed_path = FilePath(components.front());
    first_component = 1;
  } else if (!GetCurrentDirectory(&collapsed_path)) {
    return std::nullopt;
  }

  for (size_t i = first_component; i < components.size(); ++i) {
    const FilePath::StringType& component = components[i];
    if (component == FilePath::kCurrentDirectory) {
      continue;
    }
    if (component == FilePath::kParentDirectory) {
      collapsed_path = collapsed_path.DirName();
      continue;
    }
    collapsed_path = collapsed_path.Append(component);
  }
  return collapsed_path;
}

bool DeleteFile(const FilePath& path) {
  return DeletePath(path, /*recursive=*/false);
}

bool DeletePathRecursively(const FilePath& path) {
  return DeletePath(path, /*recursive=*/true);
}

bool ReplaceFile(const FilePath& from_path,
                 const FilePath& to_path,
                 File::Error* error) {
  if (rename(from_path.value().c_str(), to_path.value().c_str()) == 0) {
    return true;
  }
  if (error) {
    *error = File::GetLastFileError();
  }
  return false;
}

bool CopyFile(const FilePath& from_path, const FilePath& to_path) {
  File input(from_path, File::FLAG_OPEN | File::FLAG_READ);
  if (!input.IsValid()) {
    return false;
  }
  File output(to_path, File::FLAG_CREATE_ALWAYS | File::FLAG_WRITE);
  return output.IsValid() && CopyFileContents(input, output);
}

bool CopyDirectory(const FilePath& from_path,
                   const FilePath& to_path,
                   bool recursive) {
  return CopyDirectoryImpl(from_path, to_path, recursive,
                           /*open_exclusive=*/false);
}

bool CopyDirectoryExcl(const FilePath& from_path,
                       const FilePath& to_path,
                       bool recursive) {
  return CopyDirectoryImpl(from_path, to_path, recursive,
                           /*open_exclusive=*/true);
}

bool PathExists(const FilePath& path) {
  return access(path.value().c_str(), F_OK) == 0;
}

bool PathIsReadable(const FilePath& path) {
  return access(path.value().c_str(), R_OK) == 0;
}

bool PathIsWritable(const FilePath& path) {
  return access(path.value().c_str(), W_OK) == 0;
}

bool DirectoryExists(const FilePath& path) {
  stat_wrapper_t info;
  return File::Stat(path, &info) == 0 && S_ISDIR(info.st_mode);
}

bool ReadFromFD(int fd, span<char> buffer) {
  while (!buffer.empty()) {
    const ssize_t bytes_read =
        HANDLE_EINTR(read(fd, buffer.data(), buffer.size()));
    if (bytes_read <= 0) {
      return false;
    }
    buffer = buffer.subspan(checked_cast<size_t>(bytes_read));
  }
  return true;
}

ScopedFD CreateAndOpenFdForTemporaryFileInDir(const FilePath& directory,
                                              FilePath* path) {
  std::string name =
      TemporaryNameTemplate(directory, /*prefix=*/"", /*hidden=*/true).value();
  const int fd = HANDLE_EINTR(mkstemp(name.data()));
  if (fd < 0) {
    return ScopedFD();
  }
  *path = FilePath(std::move(name));
  return ScopedFD(fd);
}

bool GetTempDir(FilePath* path) {
  FilePath candidate("/tmp");
  if (!DirectoryExists(candidate)) {
    return false;
  }
  *path = std::move(candidate);
  return true;
}

FilePath GetHomeDir() {
  FilePath candidate("/home/web_user");
  return DirectoryExists(candidate) ? candidate : FilePath();
}

File CreateAndOpenTemporaryFileInDir(const FilePath& directory,
                                     FilePath* temp_file,
                                     uint32_t additional_flags) {
  // POSIX-style descriptors do not have additional open flags in this API.
  if (additional_flags != 0) {
    return File(File::FILE_ERROR_INVALID_OPERATION);
  }
  ScopedFD fd =
      CreateAndOpenFdForTemporaryFileInDir(directory, temp_file);
  return fd.is_valid() ? File(std::move(fd))
                       : File(File::GetLastFileError());
}

bool CreateTemporaryFileInDir(const FilePath& directory,
                              FilePath* temp_file) {
  ScopedFD fd =
      CreateAndOpenFdForTemporaryFileInDir(directory, temp_file);
  return fd.is_valid();
}

FilePath FormatTemporaryFileName(FilePath::StringViewType identifier,
                                 bool hidden) {
  std::string name = hidden ? "." : "";
  name.append("org.chromium.Chromium");
  name.push_back('.');
  name.append(identifier);
  return FilePath(std::move(name));
}

ScopedFILE CreateAndOpenTemporaryStreamInDir(const FilePath& directory,
                                             FilePath* path) {
  ScopedFD fd = CreateAndOpenFdForTemporaryFileInDir(directory, path);
  if (!fd.is_valid()) {
    return nullptr;
  }
  const int raw_fd = fd.release();
  FILE* stream = fdopen(raw_fd, "a+");
  if (!stream) {
    IGNORE_EINTR(close(raw_fd));
  }
  return ScopedFILE(stream);
}

bool CreateNewTempDirectory(FilePath::StringViewType prefix,
                            FilePath* new_temp_path) {
  FilePath temp_dir;
  return GetTempDir(&temp_dir) &&
         CreateTemporaryDirInDir(temp_dir, prefix, new_temp_path);
}

bool CreateTemporaryDirInDir(const FilePath& base_dir,
                             FilePath::StringViewType prefix,
                             FilePath* new_dir) {
  std::string name =
      TemporaryNameTemplate(base_dir, prefix, /*hidden=*/false).value();
  if (!mkdtemp(name.data())) {
    return false;
  }
  *new_dir = FilePath(std::move(name));
  return true;
}

bool CreateDirectoryAndGetError(const FilePath& full_path, File::Error* error) {
  if (DirectoryExists(full_path)) {
    return true;
  }

  std::vector<FilePath> missing_paths{full_path};
  FilePath previous = full_path;
  for (FilePath parent = full_path.DirName(); parent != previous;
       parent = parent.DirName()) {
    if (DirectoryExists(parent)) {
      break;
    }
    missing_paths.push_back(parent);
    previous = parent;
  }

  for (auto it = missing_paths.rbegin(); it != missing_paths.rend(); ++it) {
    if (File::Mkdir(*it, S_IRWXU) == 0) {
      continue;
    }
    const int saved_errno = errno;
    if (DirectoryExists(*it)) {
      continue;
    }
    if (error) {
      *error = File::OSErrorToFileError(saved_errno);
    }
    errno = saved_errno;
    return false;
  }
  return true;
}

bool CreateDirectory(const FilePath& full_path) {
  return CreateDirectoryAndGetError(full_path, nullptr);
}

bool NormalizeFilePath(const FilePath& path, FilePath* normalized_path) {
  FilePath absolute = MakeAbsoluteFilePath(path);
  if (absolute.empty()) {
    return false;
  }
  *normalized_path = std::move(absolute);
  return true;
}

bool IsLink(const FilePath& file_path) {
  stat_wrapper_t info;
  return File::Lstat(file_path, &info) == 0 && S_ISLNK(info.st_mode);
}

bool GetFileInfo(const FilePath& file_path, File::Info* results) {
  stat_wrapper_t info;
  if (File::Stat(file_path, &info) != 0) {
    return false;
  }
  results->FromStat(info);
  return true;
}

FILE* OpenFile(const FilePath& filename, base::cstring_view mode) {
  // Wasm has no child process to inherit this descriptor, so adding a
  // close-on-exec mode would claim a process semantic that does not exist.
  FILE* result;
  do {
    result = fopen(filename.value().c_str(), mode.c_str());
  } while (!result && errno == EINTR);
  return result;
}

FILE* FileToFILE(File file, const char* mode) {
  const int fd = file.TakePlatformFile();
  if (fd < 0) {
    return nullptr;
  }
  FILE* stream = fdopen(fd, mode);
  if (!stream) {
    IGNORE_EINTR(close(fd));
  }
  return stream;
}

File FILEToFile(FILE* file_stream) {
  if (!file_stream) {
    return File();
  }
  const int fd = HANDLE_EINTR(dup(fileno(file_stream)));
  return fd >= 0 ? File(ScopedFD(fd)) : File(File::GetLastFileError());
}

std::optional<uint64_t> ReadFile(const FilePath& filename, span<char> buffer) {
  ScopedFD fd(HANDLE_EINTR(open(filename.value().c_str(), O_RDONLY)));
  if (!fd.is_valid()) {
    return std::nullopt;
  }
  const size_t bytes_to_read =
      static_cast<size_t>(checked_cast<int>(buffer.size()));
  const ssize_t bytes_read =
      HANDLE_EINTR(read(fd.get(), buffer.data(), bytes_to_read));
  if (bytes_read < 0) {
    return std::nullopt;
  }
  return checked_cast<uint64_t>(bytes_read);
}

std::optional<uint64_t> ReadFile(const FilePath& filename,
                                 span<uint8_t> buffer) {
  return ReadFile(filename, as_writable_chars(buffer));
}

int ReadFile(const FilePath& filename, char* data, int max_size) {
  if (max_size < 0) {
    return -1;
  }
  std::optional<uint64_t> result =
      ReadFile(filename, span(data, checked_cast<size_t>(max_size)));
  return result.has_value() ? checked_cast<int>(*result) : -1;
}

bool ReadFileToStringWithMaxSize(const FilePath& filename,
                                 std::string* contents,
                                 size_t max_size) {
  if (contents) {
    contents->clear();
  }
  if (filename.ReferencesParent()) {
    return false;
  }

  ScopedFD fd(HANDLE_EINTR(open(filename.value().c_str(), O_RDONLY)));
  if (!fd.is_valid()) {
    return false;
  }
  stat_wrapper_t info;
  if (File::Fstat(fd.get(), &info) != 0 || info.st_size < 0 ||
      !IsValueInRangeForNumericType<size_t>(info.st_size)) {
    return false;
  }

  const size_t file_size = checked_cast<size_t>(info.st_size);
  const size_t bytes_to_read = std::min(file_size, max_size);
  std::string value(bytes_to_read, '\0');
  if (bytes_to_read != 0 && !ReadFromFD(fd.get(), span(value))) {
    return false;
  }
  if (contents) {
    *contents = std::move(value);
  }
  return file_size <= max_size;
}

bool ReadFileToString(const FilePath& filename, std::string* contents) {
  return ReadFileToStringWithMaxSize(filename, contents,
                                     std::numeric_limits<size_t>::max());
}

bool WriteFile(const FilePath& filename, span<const uint8_t> data) {
  ScopedFD fd(
      HANDLE_EINTR(open(filename.value().c_str(), O_CREAT | O_TRUNC | O_WRONLY,
                        0666)));
  return fd.is_valid() && WriteFileDescriptor(fd.get(), data);
}

bool WriteFile(const FilePath& filename, std::string_view data) {
  return WriteFile(filename, as_byte_span(data));
}

bool WriteFileDescriptor(int fd, span<const uint8_t> data) {
  while (!data.empty()) {
    const ssize_t written =
        HANDLE_EINTR(write(fd, data.data(), data.size()));
    if (written <= 0) {
      return false;
    }
    data = data.subspan(checked_cast<size_t>(written));
  }
  return true;
}

bool WriteFileDescriptor(int fd, std::string_view data) {
  return WriteFileDescriptor(fd, as_byte_span(data));
}

bool AppendToFile(const FilePath& filename, span<const uint8_t> data) {
  ScopedFD fd(
      HANDLE_EINTR(open(filename.value().c_str(), O_APPEND | O_WRONLY)));
  return fd.is_valid() && WriteFileDescriptor(fd.get(), data);
}

bool AppendToFile(const FilePath& filename, std::string_view data) {
  return AppendToFile(filename, as_byte_span(data));
}

std::optional<int64_t> GetFileSize(const FilePath& file_path) {
  File::Info info;
  if (!GetFileInfo(file_path, &info)) {
    return std::nullopt;
  }
  return info.size;
}

bool GetCurrentDirectory(FilePath* path) {
  char buffer[PATH_MAX];
  if (!getcwd(buffer, sizeof(buffer))) {
    return false;
  }
  *path = FilePath(buffer);
  return true;
}

bool SetCurrentDirectory(const FilePath& path) {
  return chdir(path.value().c_str()) == 0;
}

bool SetNonBlocking(int /*fd*/) {
  // MEMFS files cannot block, while Emscripten's F_SETFL only records
  // O_NONBLOCK without providing a stronger I/O guarantee. Do not report that
  // an unsupported descriptor mode was installed.
  errno = ENOTSUP;
  return false;
}

bool PreReadFile(const FilePath& file_path,
                 bool /*is_executable*/,
                 bool /*sequential*/,
                 int64_t max_bytes) {
  if (max_bytes < 0) {
    return false;
  }

  File file(file_path, File::FLAG_OPEN | File::FLAG_READ);
  if (!file.IsValid()) {
    return false;
  }

  std::vector<uint8_t> buffer(64 * 1024);
  int64_t remaining = max_bytes;
  while (remaining > 0) {
    const size_t requested =
        static_cast<size_t>(std::min<int64_t>(remaining, buffer.size()));
    std::optional<size_t> count =
        file.ReadAtCurrentPos(span(buffer).first(requested));
    if (!count.has_value()) {
      return false;
    }
    if (*count == 0) {
      break;
    }
    remaining -= checked_cast<int64_t>(*count);
  }
  return true;
}

int GetMaximumPathComponentLength(const FilePath& path) {
  return saturated_cast<int>(pathconf(path.value().c_str(), _PC_NAME_MAX));
}

namespace internal {

bool MoveUnsafe(const FilePath& from_path, const FilePath& to_path) {
  stat_wrapper_t destination_info;
  if (File::Stat(to_path, &destination_info) == 0) {
    stat_wrapper_t source_info;
    if (File::Stat(from_path, &source_info) != 0 ||
        S_ISDIR(destination_info.st_mode) != S_ISDIR(source_info.st_mode)) {
      return false;
    }
  }

  // M1 uses one MEMFS namespace. Do not report success if rename fails, and do
  // not silently emulate cross-mount moves with unverified persistence rules.
  return rename(from_path.value().c_str(), to_path.value().c_str()) == 0;
}

}  // namespace internal
}  // namespace base
