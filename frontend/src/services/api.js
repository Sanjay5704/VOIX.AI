import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "";

export const api = axios.create({
  baseURL,
  timeout: 120000,
});

/**
 * Normalizes backend error responses (see app.core.exceptions /
 * main.py exception handlers) into a consistent shape for the UI.
 */
function unwrapError(error) {
  if (error.response && error.response.data) {
    const { message, error_code, details } = error.response.data;
    return {
      message: message || "Something went wrong. Please try again.",
      code: error_code || "unknown_error",
      details: details || {},
      status: error.response.status,
    };
  }
  if (error.request) {
    return {
      message:
        "Couldn't reach the server. Make sure the backend is running and reachable.",
      code: "network_error",
      details: {},
      status: 0,
    };
  }
  return { message: error.message, code: "client_error", details: {}, status: 0 };
}

export async function fetchVoices() {
  try {
    const { data } = await api.get("/api/v1/voices");
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export async function generateSpeech(payload) {
  try {
    const { data } = await api.post("/api/v1/generate", payload);
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export async function generateBatch(payload) {
  try {
    const { data } = await api.post("/api/v1/generate/batch", payload);
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export async function cloneVoice(file, name) {
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name || "");
    const { data } = await api.post("/api/v1/voices/clone", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export async function deleteVoice(voiceId) {
  try {
    const { data } = await api.delete(`/api/v1/voices/${voiceId}`);
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export async function fetchHealth() {
  try {
    const { data } = await api.get("/api/v1/health");
    return data;
  } catch (err) {
    throw unwrapError(err);
  }
}

export function resolveAssetUrl(path) {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${baseURL}${path}`;
}
