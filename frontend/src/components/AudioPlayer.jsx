import React, { useEffect, useRef, useState } from "react";
import Waveform from "./Waveform.jsx";

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function AudioPlayer({ result }) {
  const audioRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [activeSentence, setActiveSentence] = useState(-1);

  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setActiveSentence(-1);
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
  }, [result?.job_id]);

  if (!result) return null;

  const { audioUrl, srtUrl, duration_seconds, sentences, format } = result;

  const togglePlay = () => {
    const el = audioRef.current;
    if (!el) return;
    if (isPlaying) {
      el.pause();
    } else {
      el.play();
    }
  };

  const handleTimeUpdate = () => {
    const el = audioRef.current;
    if (!el) return;
    setCurrentTime(el.currentTime);
    const idx = sentences.findIndex(
      (s) => el.currentTime >= s.start && el.currentTime < s.end
    );
    setActiveSentence(idx);
  };

  const seekTo = (time) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time;
      audioRef.current.play();
    }
  };

  const progressPct = duration_seconds > 0 ? (currentTime / duration_seconds) * 100 : 0;

  return (
    <div className="player">
      <audio
        ref={audioRef}
        src={audioUrl}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        onTimeUpdate={handleTimeUpdate}
      />

      <div className="player__top">
        <button
          type="button"
          className="player__play-btn"
          onClick={togglePlay}
          aria-label={isPlaying ? "Pause" : "Play"}
        >
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>

        <div className="player__visual">
          <Waveform active={isPlaying} bars={56} />
          <div
            className="player__progress-overlay"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="player__time">
          {formatTime(currentTime)} <span className="player__time-sep">/</span>{" "}
          {formatTime(duration_seconds)}
        </div>
      </div>

      <div className="player__actions">
        <a
          className="download-button download-button--primary"
          href={audioUrl}
          download={`speech.${format}`}
        >
          Download .{format}
        </a>
        {srtUrl && (
          <a className="download-button" href={srtUrl} download="subtitles.srt">
            Download .srt
          </a>
        )}
      </div>

      {sentences && sentences.length > 0 && (
        <div className="transcript">
          <p className="transcript__label">Transcript &amp; timestamps</p>
          <div className="transcript__list">
            {sentences.map((s, i) => (
              <button
                key={s.index}
                type="button"
                className={`transcript__line ${
                  i === activeSentence ? "transcript__line--active" : ""
                }`}
                onClick={() => seekTo(s.start)}
              >
                <span className="transcript__timestamp">{formatTime(s.start)}</span>
                <span className="transcript__text">{s.text}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PlayIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}
