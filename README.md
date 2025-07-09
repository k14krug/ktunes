# kTunes

kTunes is a web-based application designed to bridge the gap between your local iTunes library and Spotify. It allows you to manage your music, create intelligent playlists, and seamlessly synchronize them with Spotify. This tool is perfect for music enthusiasts who want to leverage the power of Spotify's streaming capabilities while still maintaining their curated iTunes library.

## Features

*   **iTunes Library Integration:** kTunes reads your iTunes library file (`iTunes Music Library.xml`) to access your playlists, track metadata, and play counts.
*   **Spotify Integration:** Connect your Spotify account to kTunes to:
    *   Create and update Spotify playlists based on your iTunes data.
    *   Resolve mismatches between your local tracks and their Spotify equivalents.
    *   Identify tracks in your iTunes library that are not available on Spotify.
*   **Intelligent Playlist Generation:** Create dynamic playlists based on criteria such as:
    *   Recently added tracks
    *   Most played songs
    *   Songs in rotation
    *   Customizable categories and percentages
*   **Mismatch Resolution:** A dedicated interface to resolve discrepancies between your iTunes and Spotify libraries. The system identifies potential matches and allows you to confirm or manually link tracks.
*   **Web-Based UI:** A user-friendly web interface built with Flask to manage your music library and playlists from any device on your network.
*   **Scheduled Tasks:** Automatically update your Spotify playlists at regular intervals.

## Tech Stack

*   **Backend:** Python, Flask
*   **Database:** SQLite (with SQLAlchemy and Flask-Migrate)
*   **Frontend:** HTML, CSS, JavaScript (with Jinja2 templating)
*   **Authentication:** Flask-Login
*   **Scheduling:** APScheduler
*   **APIs:** Spotify Web API, OpenAI API (for potential future enhancements)

## Installation and Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/kTunes.git
    cd kTunes
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file in the root directory and add your Spotify API credentials:
    ```
    SPOTIPY_CLIENT_ID=your_spotify_client_id
    SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
    OPENAI_API_KEY=your_openai_api_key
    ```

4.  **Configure the application:**
    The first time you run the application, it will create a `config.json` file in the root directory. You will need to edit this file to specify the path to your iTunes library file.

    ```json
    {
        "itunes_dir": "/path/to/your/itunes/music/folder",
        "itunes_lib": "iTunes Music Library.xml",
        ...
    }
    ```

5.  **Run the application:**
    ```bash
    python run.py
    ```
    The application will be accessible at `http://localhost:5003`.

## Usage

1.  **Login:** Create an account and log in to the application.
2.  **Connect to Spotify:** Authorize kTunes to access your Spotify account.
3.  **Create Playlists:** Use the playlist creation tools to generate new playlists based on your desired criteria.
4.  **Resolve Mismatches:** Navigate to the "Resolve" section to manage any discrepancies between your iTunes and Spotify libraries.
5.  **Enjoy your music!** Your new playlists will be available in your Spotify account.
