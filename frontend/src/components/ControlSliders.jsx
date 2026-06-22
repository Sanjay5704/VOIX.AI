import React from "react";

export default function ControlSliders({
  speed,
  onSpeedChange,
  pitch,
  onPitchChange,
  emotion,
  onEmotionChange,
  disabled,
}) {
  return (
    <div className="controls-grid">
      <SliderField
        label="Speed"
        value={speed}
        min={0.5}
        max={2.0}
        step={0.05}
        format={(v) => `${v.toFixed(2)}×`}
        onChange={onSpeedChange}
        disabled={disabled}
      />
      <SliderField
        label="Pitch"
        value={pitch}
        min={-12}
        max={12}
        step={0.5}
        format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)} st`}
        onChange={onPitchChange}
        disabled={disabled}
      />
      <SliderField
        label="Expressiveness"
        value={emotion}
        min={0.4}
        max={1.6}
        step={0.05}
        format={(v) => (v < 0.85 ? "Calm" : v > 1.15 ? "Animated" : "Natural")}
        onChange={onEmotionChange}
        disabled={disabled}
      />
    </div>
  );
}

function SliderField({ label, value, min, max, step, format, onChange, disabled }) {
  return (
    <div className="slider-field">
      <div className="slider-field__row">
        <span className="slider-field__label">{label}</span>
        <span className="slider-field__value">{format(value)}</span>
      </div>
      <input
        type="range"
        className="slider"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </div>
  );
}
