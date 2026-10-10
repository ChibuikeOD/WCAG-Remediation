"""Expose the backend package when Vercel mounts its directory as service root.

Locally the repository root contains the outer ``backend`` package. In the
Vercel service, that outer directory becomes the import root, so this inner
package extends its module search path back to the service root.
"""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parent.parent))
