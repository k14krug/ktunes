# services/base_playlist_engine.py
from abc import ABC, abstractmethod

class BasePlaylistEngine(ABC):
    """
    Abstract base class for a playlist generation engine.
    """
    
    # A unique identifier for the engine
    ENGINE_ID = "base"
    # A user-friendly name for the engine
    ENGINE_NAME = "Base Engine"

    def __init__(self, user, config):
        """
        Initialize the engine with a user object and a configuration dictionary.
        """
        self.user = user
        self.config = config
        self.playlist = []

    @abstractmethod
    def generate(self):
        """
        The main method to generate the playlist.
        Should return a list of track dictionaries and a stats dictionary.
        """
        pass

    @staticmethod
    @abstractmethod
    def get_configuration_form():
        """
        Returns the Flask-WTF form class used to configure this engine.
        This allows the UI to dynamically generate the correct form.
        """
        pass

    def save_to_database(self, playlist_name):
        """
        A common method to save the generated playlist.
        This could be part of the base class to avoid code duplication.
        """
        # ... (common database saving logic) ...
        pass
