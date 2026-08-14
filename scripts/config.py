import json
import os

CONFIG_PATH = os.path.expanduser(
        "~/.config/infinite-canvas/config.json"
)

DEFAULT_CONFIG = {
        "workspace": None,
        "monitor": None,

    "zoom": {
		"enabled": True,
		"base_factor": 1.05,

		"acceleration": {
        "enabled": False,
		"strength": 0.50
	},
        "momentum": {
            "enabled": False,
            "strength": 0.15,
            "decay": 0.25
            }
    },

	"pan": {
		"speed": 1.0
	}
}

def load_config():
    
    # Extracts directory that the file should exist in per CONFIG_PATH.
    config_directory = os.path.dirname(CONFIG_PATH)

    # Creates the directory same as wehre the CONFIG_PATH should be.
    # exist_ok=True so that if it does exist, error isn't raised.
    os.makedirs(config_directory, exist_ok=True)

    # If the CONFIG_FILE doesn't exist, create one.
    if not os.path.exists(CONFIG_PATH):

        # Using the intended path.
        with open(CONFIG_PATH, "w") as f:
            # Dumps the default config into the file.
            json.dump(
                    DEFAULT_CONFIG, f, indent=2
                    )
        
        # Returns the default configuration because the path wasn't present.
        return DEFAULT_CONFIG

    # JSON data in config file returns as Python dictionary.
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


