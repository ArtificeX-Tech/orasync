class OrasyncError(Exception):
    """Base class for user-facing orasync failures."""


class UnsafeArchiveError(OrasyncError):
    """Raised when an ORA archive contains unsafe paths or entries."""


class ArchiveFormatError(OrasyncError):
    """Raised when an ORA archive does not look like OpenRaster."""


class ProjectLayoutError(OrasyncError):
    """Raised when a project directory cannot safely be used."""


class GitError(OrasyncError):
    """Raised when a git command fails."""

    def __init__(self, message, *, command=None, returncode=None, stdout="", stderr=""):
        super().__init__(message)
        self.command = command or []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class DirtyRepoError(GitError):
    """Raised when a clean Git working tree is required."""


class LockError(OrasyncError):
    """Raised when another orasync process owns the project lock."""

