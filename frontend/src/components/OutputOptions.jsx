import React from "react";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "it", label: "Italian" },
  { code: "pt", label: "Portuguese" },
  { code: "pl", label: "Polish" },
  { code: "hi", label: "Hindi" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "zh-cn", label: "Chinese" },
];

export default function OutputOptions({
  language,
  onLanguageChange,
  format,
  onFormatChange,
  generateSubtitles,
  onGenerateSubtitlesChange,
  disabled,
}) {
  return (
    <div className="output-options">
      <label className="field field--inline">
        <span className="field__label">Language</span>
        <select
          className="select"
          value={language}
          onChange={(e) => onLanguageChange(e.target.value)}
          disabled={disabled}
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </label>

      <label className="field field--inline">
        <span className="field__label">Format</span>
        <select
          className="select"
          value={format}
          onChange={(e) => onFormatChange(e.target.value)}
          disabled={disabled}
        >
          <option value="wav">WAV</option>
          <option value="mp3">MP3</option>
        </select>
      </label>

      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={generateSubtitles}
          onChange={(e) => onGenerateSubtitlesChange(e.target.checked)}
          disabled={disabled}
        />
        <span>Generate .srt subtitles</span>
      </label>
    </div>
  );
}
