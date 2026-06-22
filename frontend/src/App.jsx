import React, { useEffect, useState } from "react";
import Header from "./components/Header.jsx";
import TextInput from "./components/TextInput.jsx";
import VoiceSelector from "./components/VoiceSelector.jsx";
import ControlSliders from "./components/ControlSliders.jsx";
import OutputOptions from "./components/OutputOptions.jsx";
import GenerateButton from "./components/GenerateButton.jsx";
import AudioPlayer from "./components/AudioPlayer.jsx";
import ErrorBanner from "./components/ErrorBanner.jsx";
import CloneVoiceModal from "./components/CloneVoiceModal.jsx";
import Waveform from "./components/Waveform.jsx";
import { useVoices } from "./hooks/useVoices.js";
import { useSpeechGeneration } from "./hooks/useSpeechGeneration.js";
import { fetchHealth } from "./services/api.js";

export default function App() {
  const { voices, loading: voicesLoading, error: voicesError, reload: reloadVoices } =
    useVoices();
  const { isGenerating, result, error, generate, reset } = useSpeechGeneration();

  const [text, setText] = useState(
    "Welcome to NaturalSpeech. Type anything you like, choose a voice, and press generate — pauses, emphasis, and rhythm follow your punctuation automatically."
  );
  const [voiceId, setVoiceId] = useState("male");
  const [speed, setSpeed] = useState(1.0);
  const [pitch, setPitch] = useState(0.0);
  const [emotion, setEmotion] = useState(1.0);
  const [language, setLanguage] = useState("en");
  const [format, setFormat] = useState("wav");
  const [generateSubtitles, setGenerateSubtitles] = useState(true);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function poll() {
      try {
        const data = await fetchHealth();
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth(null);
      }
      timer = setTimeout(poll, 5000);
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const handleGenerate = async () => {
    if (!text.trim()) return;
    try {
      await generate({
        text,
        voice_id: voiceId,
        language,
        speed,
        pitch_semitones: pitch,
        output_format: format,
        generate_subtitles: generateSubtitles,
        emotion_exaggeration: emotion,
      });
    } catch {
      // error state already captured by the hook
    }
  };

  const handleVoiceCloned = (cloneResult) => {
    setCloneModalOpen(false);
    reloadVoices();
    setVoiceId(cloneResult.voice_id);
  };

  const canGenerate = text.trim().length > 0 && !isGenerating;

  return (
    <div className="app">
      <Header health={health} />

      <main className="layout">
        <section className="hero">
          <Waveform active={isGenerating} bars={80} />
          <h1 className="hero__title">Speech that sounds like someone, not something.</h1>
          <p className="hero__subtitle">
            Open-source XTTS-v2 synthesis running locally — natural pacing,
            real punctuation handling, and a voice you can clone in seconds.
          </p>
        </section>

        <ErrorBanner error={error} onDismiss={reset} />
        <ErrorBanner error={voicesError} />

        <section className="workspace">
          <div className="workspace__column">
            <TextInput value={text} onChange={setText} disabled={isGenerating} />

            <VoiceSelector
              voices={voices}
              selectedId={voiceId}
              onSelect={setVoiceId}
              disabled={isGenerating || voicesLoading}
              onOpenClone={() => setCloneModalOpen(true)}
            />

            <ControlSliders
              speed={speed}
              onSpeedChange={setSpeed}
              pitch={pitch}
              onPitchChange={setPitch}
              emotion={emotion}
              onEmotionChange={setEmotion}
              disabled={isGenerating}
            />

            <OutputOptions
              language={language}
              onLanguageChange={setLanguage}
              format={format}
              onFormatChange={setFormat}
              generateSubtitles={generateSubtitles}
              onGenerateSubtitlesChange={setGenerateSubtitles}
              disabled={isGenerating}
            />

            <GenerateButton
              onClick={handleGenerate}
              isGenerating={isGenerating}
              disabled={!canGenerate}
            />
          </div>

          <div className="workspace__column workspace__column--output">
            {result ? (
              <AudioPlayer result={result} />
            ) : (
              <div className="player-placeholder">
                <Waveform bars={56} />
                <p>Your generated audio will appear here, ready to play and download.</p>
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="footer">
        <span>NaturalSpeech · powered by Coqui XTTS-v2 · runs locally</span>
      </footer>

      <CloneVoiceModal
        open={cloneModalOpen}
        onClose={() => setCloneModalOpen(false)}
        onCloned={handleVoiceCloned}
      />
    </div>
  );
}
