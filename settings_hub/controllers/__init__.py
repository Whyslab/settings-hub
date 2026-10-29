"""Page logic without GTK: what to write when, and what a re-read may overwrite.

A page module (settings_hub.pages.*) builds the widgets and forwards their
signals here; a controller talks to its backend and to History and updates
the page through a small view interface. Keeping this free of GTK lets the
timing rules be tested with a fake clock.
"""
