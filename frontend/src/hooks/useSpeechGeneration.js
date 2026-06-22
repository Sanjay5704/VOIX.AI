import { useCallback, useState } from "react";
import { generateSpeech } from "../services/api.js";
import { resolveAssetUrl } from "../services/api.js";

const STATUS = {
  IDLE: "idle",
  GENERATING: "generating",
  SUCCESS: "success",
  ERROR: "error",
};

export function useSpeechGeneration() {
  const [status, setStatus] = useState(STATUS.IDLE);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const generate = useCallback(async (params) => {
    setStatus(STATUS.GENERATING);
    setError(null);
    setResult(null);
    try {
      const data = await generateSpeech(params);
      setResult({
        ...data,
        audioUrl: resolveAssetUrl(data.audio_url),
        srtUrl: resolveAssetUrl(data.srt_url),
      });
      setStatus(STATUS.SUCCESS);
      return data;
    } catch (err) {
      setError(err);
      setStatus(STATUS.ERROR);
      throw err;
    }
  }, []);

  const reset = useCallback(() => {
    setStatus(STATUS.IDLE);
    setResult(null);
    setError(null);
  }, []);

  return {
    status,
    isGenerating: status === STATUS.GENERATING,
    result,
    error,
    generate,
    reset,
  };
}

export { STATUS as GENERATION_STATUS };
