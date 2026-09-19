"""Read factory and sheet metadata after Dia has finished loading its plugins."""


def discover(dia):
    # Do not instantiate factories: listing an unfamiliar type must not create objects.
    return {
        "api_version": "1",
        "object_types": [
            {"name": kind.name, "version": kind.version}
            for kind in sorted(dia.registered_types().values(), key=lambda kind: kind.name)
        ],
        "sheets": [
            {
                "name": sheet.name,
                "description": sheet.description,
                "user": bool(sheet.user),
                "objects": [
                    {"type": kind.name if kind else None, "description": description}
                    for kind, description, _icon in sheet.objects
                ],
            }
            for sheet in sorted(dia.registered_sheets(), key=lambda sheet: sheet.name)
        ],
    }
