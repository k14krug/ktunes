import json
import os
def load_config(force_defaults=False):
    default_config = {
        'itunes_dir': '/mnt/c/Users/nwkru/Music/iTunes',
        'itunes_lib': 'iTunes Music Library.xml',
        'playlist_defaults': {
            'playlist_length': 40.0,
            'minimum_recent_add_playcount': 15,
            'categories': [
                {'name': 'RecentAdd', 'percentage': 20.0, 'artist_repeat': 21},
                {'name': 'Latest', 'percentage': 25.0, 'artist_repeat': 21},
                {'name': 'In Rot', 'percentage': 35.0, 'artist_repeat': 40},
                {'name': 'Other', 'percentage': 10.0, 'artist_repeat': 200},
                {'name': 'Old', 'percentage': 7.0, 'artist_repeat': 200},
                {'name': 'Album', 'percentage': 3.0, 'artist_repeat': 200}
            ]
        }
    }

    config_path = 'config.json'

    if force_defaults:
        if os.path.exists(config_path):
            print("Loading default config without rewriting the existing config file")
            return default_config
        else:
            print("Creating default config file")
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config
    else:
        if os.path.exists(config_path):
            print("Loading config from file")
            with open(config_path, 'r') as f:
                return json.load(f)
        else:
            print("Creating default config file")
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config
        
def dump_config(config: dict, keys_to_dump=None) -> dict:
    """
    Return a filtered copy of config containing only the keys specified.
    If keys_to_dump is None, persist only a default set of keys.
    This function allows you to only write out a subset of the config that 
    you want to be persisted (like not writing out passwords and api keys).
    """
    if keys_to_dump is None:
        keys_to_dump = [
            'itunes_dir',
            'itunes_lib',
            'playlist_defaults'
        ]
    return { key: config[key] for key in keys_to_dump if key in config }