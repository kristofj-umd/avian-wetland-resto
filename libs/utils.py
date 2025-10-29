# function to transform nice string into a name
# replacing spaces and other non-alphanumeric characters with underscores
def _nice_string_to_name(nice_string: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", nice_string.replace(" ", "_")).lower()
