# Shared in-memory session state, kept out of the plugin modules themselves
# to avoid circular imports (auto_post.py and file_rename.py both need this).

# auto_post_sessions[user_id] = {'channel_id': int, 'channel_title': str, 'format': dict}
auto_post_sessions = {}
