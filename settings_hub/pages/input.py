"""The "Keyboard and mouse" page: layouts, repeat, mouse and touchpad (the cursor
is on the Appearance page).

The rows come from the variable table (variables/__init__.py: page "input"),
so the page itself is the shared VariablesPage.
"""

from .variables import VariablesPage

PAGE = VariablesPage
