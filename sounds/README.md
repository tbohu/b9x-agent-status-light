# Local voice files

Voice files are intentionally not distributed with this project.

To enable alerts, create `local_sounds/` at the repository root and add:

- `working.wav`
- `attention.wav`
- `idle.wav`

Run `./install.sh` again. The installer copies only these three files to the
local Application Support runtime. Make sure you have the necessary rights to
use every supplied voice and recording.
