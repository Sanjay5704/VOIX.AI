import React, { useEffect, useRef, useState } from "react";
import { useBlobUrl } from "../hooks/useData.js";
import { formatClock } from "../lib/format.js";
import Waveform from "./Waveform.jsx";

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Player for a succeeded synthesize job: waveform, transport, transcript, downloads. */
export default function AudioPlayer({ job }) {
  const audio = useBlobUrl(job?.audio_url);
  const subtitles = useBlobUrl(job?.subtitles_url);
  const el = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);

  const result = job?.result || {};
  const duration = result.duration_seconds || 0;
  const sentences = result.sentences || [];
  const format = result.format || "mp3";
  const shortId = job?.id?.slice(0, 8);

  useEffect(() => {
    setPlaying(false);
    setTime(0);
  }, [job?.id]);

  const toggle = () => {
    if (!el.current) return;
    if (el.current.paused) el.current.play();
    else el.current.pause();
  };
  const seek = (seconds) => {
    if (!el.current) return;
    el.current.currentTime = seconds;
    el.current.play();
  };
  // The cue being spoken, held through the pause that follows it.
  const active = time > 0 ? sentences.findLastIndex((s) => time >= s.start) : -1;

  if (audio.error) return <p className="notice notice--error">Couldn't load audio: {audio.error.message}</p>;

  return (
    <div className="player">
      {audio.url && (
        <audio
          ref={el}
          src={audio.url}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          preload="auto"
        />
      )}
      <div className="player__deck">
        <button
          type="button"
          className="transport"
          onClick={toggle}
          disabled={!audio.url}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? (
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path d="M8 5v14l11-7z" fill="currentColor" />
            </svg>
          )}
        </button>
        <div className="player__wave">
          <Waveform
            blob={audio.blob}
            progress={duration ? time / duration : 0}
            onSeek={(frac) => seek(frac * duration)}
          />
        </div>
        <span className="player__clock mono">
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>

      <div className="player__actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          disabled={!audio.blob}
          onClick={() => saveBlob(audio.blob, `voix-${shortId}.${format}`)}
        >
          Download .{format}
        </button>
        {job?.subtitles_url && (
          <button
            type="button"
            className="btn btn--sm"
            disabled={!subtitles.blob}
            onClick={() => saveBlob(subtitles.blob, `voix-${shortId}.srt`)}
          >
            Download .srt
          </button>
        )}
      </div>

      {sentences.length > 0 && (
        <ol className="cues">
          {sentences.map((s, i) => (
            <li key={s.index}>
              <button
                type="button"
                className={`cue ${i === active ? "cue--active" : ""}`}
                onClick={() => seek(s.start)}
              >
                <span className="cue__time mono">{formatClock(s.start)}</span>
                <span className="cue__text">{s.text}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
