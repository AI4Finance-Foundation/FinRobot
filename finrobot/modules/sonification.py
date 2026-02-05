"""
FinRobot Data Sonification Module

Converts financial time-series data (Stock Price, Volume, Volatility) into
musical MIDI sequences. This allows users to "listen" to market trends,
creating an auditory display of data for pattern recognition or algorithmic art.

Example:
    >>> from finrobot.modules.sonification import MarketSynth, generate_melody
    >>> synth = generate_melody("NVDA", "2024-01-01", "2024-12-31")
    >>> synth.save_midi("NVDA_2024.mid")
"""

from typing import Annotated, Optional, Literal
import pandas as pd
import numpy as np
from midiutil import MIDIFile

from ..data_source.yfinance_utils import YFinanceUtils


# =============================================================================
# Musical Scale Definitions
# =============================================================================
# MIDI note numbers: C4 = 60 (Middle C)
# We define scales as semitone intervals from the root note

SCALES = {
    "pentatonic": [0, 3, 5, 7, 10],  # Minor Pentatonic: C, Eb, F, G, Bb
    "pentatonic_major": [0, 2, 4, 7, 9],  # Major Pentatonic: C, D, E, G, A
    "blues": [0, 3, 5, 6, 7, 10],  # Blues: C, Eb, F, F#, G, Bb
    "chromatic": list(range(12)),  # All 12 semitones
    "dorian": [0, 2, 3, 5, 7, 9, 10],  # Dorian mode (cyberpunk/neo-noir feel)
    "minor": [0, 2, 3, 5, 7, 8, 10],  # Natural Minor
}

# Default range: C3 (48) to C6 (84) = 3 octaves
DEFAULT_NOTE_RANGE = (48, 84)


class MarketSynth:
    """
    Synthesizes market data into MIDI sequences.
    
    Transforms financial time-series data into musical notes by mapping:
    - Stock Price → MIDI Note (pitch)
    - Volume → Velocity (loudness)
    - Daily Volatility → Note Duration (optional)
    
    Attributes:
        df (pd.DataFrame): Input DataFrame with Date, Close, Volume columns.
        scale (str): Musical scale to map notes to.
        tempo (int): Beats per minute for the MIDI track.
        midi (MIDIFile): The generated MIDI file object.
        
    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'Date': pd.date_range('2024-01-01', periods=5),
        ...     'Close': [100, 105, 103, 110, 108],
        ...     'Volume': [1000000, 1500000, 1200000, 2000000, 1800000]
        ... })
        >>> synth = MarketSynth(df, scale='pentatonic')
        >>> synth.process()
        >>> synth.save_midi('output.mid')
    """
    
    def __init__(
        self,
        df: pd.DataFrame,
        scale: Literal[
            "pentatonic", "pentatonic_major", "blues", 
            "chromatic", "dorian", "minor"
        ] = "pentatonic",
        tempo: int = 120,
        note_range: tuple[int, int] = DEFAULT_NOTE_RANGE,
        root_note: int = 48,  # C3
        variable_duration: bool = False,
    ):
        """
        Initialize the MarketSynth.
        
        Args:
            df: DataFrame with columns ['Date', 'Close', 'Volume'].
                 Index can also be DatetimeIndex (from yfinance).
            scale: Musical scale preset. Options: 'pentatonic', 'pentatonic_major',
                   'blues', 'chromatic', 'dorian', 'minor'.
            tempo: Beats per minute (default: 120).
            note_range: Tuple of (min_note, max_note) MIDI values.
            root_note: The root MIDI note for scale construction.
            variable_duration: If True, map volatility to note duration.
        """
        self.df = self._validate_dataframe(df)
        self.scale_name = scale
        self.scale_intervals = SCALES.get(scale, SCALES["pentatonic"])
        self.tempo = tempo
        self.note_range = note_range
        self.root_note = root_note
        self.variable_duration = variable_duration
        
        # Build full scale across octaves
        self._scale_notes = self._build_scale()
        
        # Initialize MIDI file (1 track)
        self.midi = MIDIFile(1)
        self.midi.addTempo(0, 0, tempo)
        self.midi.addTrackName(0, 0, "Market Melody")
        
        self._processed = False
    
    def _validate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate and normalize the input DataFrame."""
        df = df.copy()
        
        # Handle yfinance-style DataFrames with DatetimeIndex
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            # yfinance returns 'Date' or sometimes index name varies
            if 'Date' not in df.columns and df.columns[0] not in ['Date']:
                df = df.rename(columns={df.columns[0]: 'Date'})
        
        # Check required columns (case-insensitive matching)
        df.columns = [str(c) for c in df.columns]
        col_map = {c.lower(): c for c in df.columns}
        
        required = ['close', 'volume']
        for req in required:
            if req not in col_map:
                raise ValueError(
                    f"DataFrame must contain '{req}' column. "
                    f"Got columns: {list(df.columns)}"
                )
        
        # Normalize column names
        df = df.rename(columns={
            col_map.get('close', 'Close'): 'Close',
            col_map.get('volume', 'Volume'): 'Volume',
        })
        
        return df
    
    def _build_scale(self) -> list[int]:
        """
        Build a list of valid MIDI notes within the specified range
        that belong to the chosen scale.
        """
        notes = []
        min_note, max_note = self.note_range
        
        # Calculate how many octaves we need
        for octave_offset in range(-2, 6):  # Cover a wide range
            for interval in self.scale_intervals:
                note = self.root_note + (octave_offset * 12) + interval
                if min_note <= note <= max_note:
                    notes.append(note)
        
        return sorted(set(notes))
    
    def _normalize(
        self, 
        series: pd.Series, 
        out_min: float = 0.0, 
        out_max: float = 1.0
    ) -> pd.Series:
        """Normalize a series to [out_min, out_max] range."""
        s_min, s_max = series.min(), series.max()
        if s_max - s_min == 0:
            return pd.Series([0.5] * len(series))
        return (series - s_min) / (s_max - s_min) * (out_max - out_min) + out_min
    
    def _map_to_scale(self, normalized_value: float) -> int:
        """
        Map a normalized value [0, 1] to a note in the scale.
        
        Args:
            normalized_value: Float between 0 and 1.
            
        Returns:
            MIDI note number from the constructed scale.
        """
        if not self._scale_notes:
            return self.root_note
        
        # Clamp value
        normalized_value = max(0.0, min(1.0, normalized_value))
        
        # Map to scale index
        index = int(normalized_value * (len(self._scale_notes) - 1))
        return self._scale_notes[index]
    
    def _calculate_volatility(self) -> pd.Series:
        """
        Calculate daily volatility as absolute percentage change.
        Used for variable note duration.
        """
        returns = self.df['Close'].pct_change().abs()
        returns = returns.fillna(returns.mean())
        return returns
    
    def process(self) -> "MarketSynth":
        """
        Process the DataFrame and generate MIDI notes.
        
        Maps:
        - Close price → Note pitch (via scale quantization)
        - Volume → Note velocity (loudness)
        - Volatility → Note duration (if variable_duration=True)
        
        Returns:
            self for method chaining.
        """
        track = 0
        channel = 0  # Piano
        
        # Normalize price to [0, 1] for scale mapping
        price_normalized = self._normalize(self.df['Close'])
        
        # Normalize volume to velocity range [40, 127]
        # (40 minimum so notes are audible)
        velocity_normalized = self._normalize(
            self.df['Volume'], out_min=40, out_max=127
        ).astype(int)
        
        # Calculate duration
        if self.variable_duration:
            volatility = self._calculate_volatility()
            # Map volatility to duration: low volatility = short (0.25), high = long (1.0)
            duration_normalized = self._normalize(
                volatility, out_min=0.25, out_max=1.0
            )
        else:
            # Constant 16th note duration (0.25 beats)
            duration_normalized = pd.Series([0.25] * len(self.df))
        
        # Generate notes
        time = 0.0  # Start time in beats
        
        for i in range(len(self.df)):
            pitch = self._map_to_scale(price_normalized.iloc[i])
            velocity = int(velocity_normalized.iloc[i])
            duration = float(duration_normalized.iloc[i])
            
            self.midi.addNote(
                track=track,
                channel=channel,
                pitch=pitch,
                time=time,
                duration=duration,
                volume=velocity,
            )
            
            # Advance time by the note duration
            time += duration
        
        self._processed = True
        return self
    
    def save_midi(self, filename: str) -> str:
        """
        Save the generated MIDI to a file.
        
        Args:
            filename: Output filename (should end in .mid or .midi).
            
        Returns:
            The filename that was saved.
            
        Raises:
            RuntimeError: If process() hasn't been called yet.
        """
        if not self._processed:
            self.process()
        
        if not filename.endswith(('.mid', '.midi')):
            filename += '.mid'
        
        with open(filename, 'wb') as f:
            self.midi.writeFile(f)
        
        print(f"[MarketSynth] Saved MIDI: {filename}")
        return filename
    
    def get_midi(self) -> MIDIFile:
        """Return the raw MIDIFile object for further manipulation."""
        if not self._processed:
            self.process()
        return self.midi
    
    def summary(self) -> dict:
        """
        Return a summary of the sonification parameters.
        
        Returns:
            Dictionary with configuration and statistics.
        """
        return {
            "data_points": len(self.df),
            "scale": self.scale_name,
            "tempo_bpm": self.tempo,
            "note_range": self.note_range,
            "scale_notes_count": len(self._scale_notes),
            "variable_duration": self.variable_duration,
            "price_range": (self.df['Close'].min(), self.df['Close'].max()),
            "volume_range": (self.df['Volume'].min(), self.df['Volume'].max()),
            "processed": self._processed,
        }


def generate_melody(
    ticker: Annotated[str, "Stock ticker symbol (e.g., 'NVDA', 'AAPL')"],
    start_date: Annotated[str, "Start date in YYYY-MM-DD format"],
    end_date: Annotated[str, "End date in YYYY-MM-DD format"],
    scale: Literal[
        "pentatonic", "pentatonic_major", "blues", 
        "chromatic", "dorian", "minor"
    ] = "pentatonic",
    tempo: int = 120,
    variable_duration: bool = False,
    save_path: Optional[str] = None,
) -> MarketSynth:
    """
    Generate a MIDI melody from stock market data.
    
    This is the main convenience function that fetches stock data and
    converts it into a musical MIDI sequence.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'NVDA', 'AAPL').
        start_date: Start date for data retrieval (YYYY-MM-DD).
        end_date: End date for data retrieval (YYYY-MM-DD).
        scale: Musical scale preset. Options:
            - 'pentatonic': Minor pentatonic (melancholic, bluesy)
            - 'pentatonic_major': Major pentatonic (bright, optimistic)
            - 'blues': Blues scale (soulful)
            - 'chromatic': All 12 notes (chaotic, atonal)
            - 'dorian': Dorian mode (cyberpunk, neo-noir)
            - 'minor': Natural minor (dark, dramatic)
        tempo: Beats per minute (default: 120).
        variable_duration: If True, volatility affects note length.
        save_path: If provided, automatically save MIDI to this path.
        
    Returns:
        MarketSynth instance with processed MIDI data.
        
    Example:
        >>> synth = generate_melody("NVDA", "2024-01-01", "2024-12-31")
        >>> synth.save_midi("NVDA_2024.mid")
        
        >>> # Or save directly
        >>> generate_melody("AAPL", "2024-01-01", "2024-06-30", 
        ...                 scale="blues", save_path="AAPL_blues.mid")
    """
    # Fetch stock data using FinRobot's YFinanceUtils
    print(f"[MarketSynth] Fetching data for {ticker} ({start_date} to {end_date})...")
    df = YFinanceUtils.get_stock_data(ticker, start_date, end_date)
    
    if df.empty:
        raise ValueError(f"No data retrieved for {ticker} in the specified date range.")
    
    print(f"[MarketSynth] Retrieved {len(df)} data points.")
    print(f"[MarketSynth] Converting to {scale} scale at {tempo} BPM...")
    
    # Create and process the synth
    synth = MarketSynth(
        df=df,
        scale=scale,
        tempo=tempo,
        variable_duration=variable_duration,
    )
    synth.process()
    
    # Optionally save
    if save_path:
        synth.save_midi(save_path)
    
    return synth


# =============================================================================
# CLI Entry Point (for testing)
# =============================================================================
if __name__ == "__main__":
    import sys
    
    # Example usage
    print("=" * 60)
    print("FinRobot Data Sonification Module")
    print("=" * 60)
    
    if len(sys.argv) >= 4:
        ticker = sys.argv[1]
        start = sys.argv[2]
        end = sys.argv[3]
        scale = sys.argv[4] if len(sys.argv) > 4 else "pentatonic"
    else:
        # Default demo
        ticker = "NVDA"
        start = "2024-01-01"
        end = "2024-12-31"
        scale = "pentatonic"
    
    print(f"\nGenerating melody for {ticker}...")
    print(f"Date range: {start} to {end}")
    print(f"Scale: {scale}")
    print("-" * 60)
    
    synth = generate_melody(ticker, start, end, scale=scale)
    
    print("\nSummary:")
    for key, value in synth.summary().items():
        print(f"  {key}: {value}")
    
    output_file = f"{ticker}_{start[:4]}.mid"
    synth.save_midi(output_file)
    
    print(f"\nDone! Open {output_file} in any MIDI player to listen.")
