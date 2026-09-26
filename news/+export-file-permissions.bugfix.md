Files written by `to_html(path)`, `write_image`, `write_images` and facet
exports now get the same permissions as any other new file (normally
`rw-r--r--`), and a file that already exists keeps its mode. They were created
owner-only (`rw-------`), so a web server or another user could not read them.
