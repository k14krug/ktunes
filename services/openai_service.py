from openai import OpenAI
import os

class OpenAIService:
    def __init__(self):
        # Initialize the OpenAI client with the API key
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        if not self.client.api_key:
            raise RuntimeError("OpenAI API key is not configured!")

    def suggest_genres(self, track_info):
        """
        Use the OpenAI API to suggest genres for tracks.

        Args:
            track_info (list): A list of dictionaries with keys "song", "artist", and optional "album".

        Returns:
            list: Suggested genres for each track.
        """
        if not track_info:
            return []

        # Construct the prompt
        prompt = "Suggest 3-5 genres for each track based on song name, artist, and album:\n"
        for track in track_info:
            prompt += f"Song: {track.get('song', 'Unknown')}, Artist: {track.get('artist', 'Unknown')}, Album: {track.get('album', 'Unknown')}\n"

        try:
            completion = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant for suggesting music genres."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.7
            )
            # Extract the content from the completion object
            suggestions = completion.choices[0].message.content.strip().split("\n")
            return [s.strip() for s in suggestions if s.strip()]
        except Exception as e:
            raise RuntimeError(f"Failed to get suggestions from OpenAI: {e}")





