import { ref } from "vue";

// 朗读：优先走后端 edge-tts（微软神经网络语音，音质佳），
// 请求失败（未安装/离线）时自动回退浏览器本地 speechSynthesis。
const supported = typeof window !== "undefined" && "speechSynthesis" in window;
const speakingId = ref(null);
let voice = null;
let token = 0;
let audioEl = null;

const pickVoice = () => {
  if (!supported) return null;
  const voices = window.speechSynthesis
    .getVoices()
    .filter((item) => /^en[-_]/i.test(item.lang));
  if (!voices.length) return null;
  const preferred = [
    /en[-_]US/i,
    /Samantha|Ava|Allison|Aria|Jenny|Google US English|Microsoft Zira/i,
    /en[-_]GB/i,
  ];
  for (const pattern of preferred) {
    const found = voices.find((item) => pattern.test(`${item.lang} ${item.name}`));
    if (found) return found;
  }
  return voices[0];
};

if (supported) {
  voice = pickVoice();
  window.speechSynthesis.onvoiceschanged = () => {
    voice = pickVoice();
  };
};

const speakLocal = (text, id, rate) => {
  const synth = window.speechSynthesis;
  synth.cancel();
  if (!voice) voice = pickVoice();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = voice?.lang || "en-US";
  if (voice) utterance.voice = voice;
  utterance.rate = rate;
  const currentToken = ++token;
  speakingId.value = id;
  utterance.onend = () => {
    if (token === currentToken) speakingId.value = null;
  };
  utterance.onerror = () => {
    if (token === currentToken) speakingId.value = null;
  };
  synth.speak(utterance);
};

const speak = async (text, { id = null, rate = 0.95 } = {}) => {
  if (!text) return;
  const currentToken = ++token;
  // 数口语速 0.95 → edge-tts 语速 "-5%"
  const ratePercent = `${rate >= 1 ? "+" : "-"}${Math.abs(Math.round((rate - 1) * 100))}%`;
  try {
    const response = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, rate: ratePercent }),
    });
    if (!response.ok) throw new Error(`tts ${response.status}`);
    const blob = await response.blob();
    if (token !== currentToken) return; // 已被下一次朗读取代
    if (audioEl) {
      audioEl.pause();
      URL.revokeObjectURL(audioEl.src);
    }
    audioEl = new Audio(URL.createObjectURL(blob));
    speakingId.value = id;
    audioEl.onended = () => {
      if (token === currentToken) speakingId.value = null;
    };
    audioEl.onerror = () => {
      if (token === currentToken) speakingId.value = null;
    };
    await audioEl.play();
  } catch {
    // 后端不可用：回退本地语音
    if (supported && token === currentToken) speakLocal(text, id, rate);
  }
};

const stop = () => {
  token += 1;
  if (audioEl) {
    audioEl.pause();
    URL.revokeObjectURL(audioEl.src);
    audioEl = null;
  }
  if (supported) window.speechSynthesis.cancel();
  speakingId.value = null;
};

export function useSpeech() {
  return { speak, stop, speakingId, supported: true };
}
