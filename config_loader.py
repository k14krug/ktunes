import json
import os
def load_config(force_defaults=False):
    default_config = {
        'itunes_dir': '/mnt/c/Users/nwkru/Music/iTunes',
        'itunes_lib': 'iTunes Library.xml',
        'playlist_defaults': {
            'playlist_length': 40.0,
            'minimum_recent_add_playcount': 15,
            'categories': [
                {'name': 'RecentAdd', 'percentage': 25.0, 'artist_repeat': 21},
                {'name': 'Latest', 'percentage': 25.0, 'artist_repeat': 21},
                {'name': 'In Rot', 'percentage': 30.0, 'artist_repeat': 40},
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