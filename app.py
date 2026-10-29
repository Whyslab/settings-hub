#!/usr/bin/env python3
"""Start settings-hub: python3 app.py [--daemon] [--page ID] [--color-scheme light|dark].

The installer copies this file next to the settings_hub package, so the same
launcher works from the repository and from ~/.local/share/settings-hub/.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from settings_hub.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv))
