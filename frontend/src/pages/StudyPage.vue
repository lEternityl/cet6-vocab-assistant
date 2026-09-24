<script setup>
import {
  ArrowLeft,
  Bot,
  Brain,
  Check,
  LoaderCircle,
  MessageCircle,
  RotateCcw,
  Sparkles,
  Timer,
  Volume2,
  VolumeX,
  X,
} from "lucide-vue-next";
import MarkdownIt from "markdown-it";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api";
import { useSpeech } from "../composables/useSpeech";
import { useAppStore } from "../stores/app";

const route = useRoute();
const router = useRouter();
const store = useAppStore();
const documentId = Number(route.params.id);
const level = route.query.level || "cet6";
const order = route.query.order || "frequency";
const mode = route.query.mode || "free";
const scope = route.query.scope || "study";
const statusFilter = route.query.status || "all";
const searchFilter = route.query.search || "";
const minFrequency = Number(route.query.min_frequency) || 0;
const reviewFilter = route.query.review_filter || "all";
const durationMinutes = Math.max(0, Number(route.query.duration) || 0);
const document = ref(null);
const queue = ref([]);
const currentIndex = ref(0);
const flipped = ref(false);
const revealed = ref(false);
const loading = ref(true);
const answering = ref(false);
const translatingExamples = ref(false);
const knownCount = ref(0);
const unknownCount = ref(0);
const remainingSeconds = ref(durationMinutes * 60);
let timerId = null;

const current = computed(() => queue.value[currentIndex.value]);
const untranslatedExamples = computed(
  () => current.value?.examples?.filter((example) => !example.translation) || [],
);
const originalCount = computed(() => queue.value.filter((item) => !item.isRepeat).length);
const progress = computed(() => {
  if (!originalCount.value) return 100;
  return Math.min(100, Math.round(((knownCount.value + unknownCount.value) / originalCount.value) * 100));
});
const finished = computed(() => !loading.value && currentIndex.value >= queue.value.length);
const formattedTime = computed(() => {
  const total = Math.max(0, remainingSeconds.value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
});

const stopTimer = () => {
  if (timerId) {
    window.clearInterval(timerId);
    timerId = null;
  }
};

// 朗读：自动播放单词（可关）+ 手动按钮（单词/例句）
const { speak, stop: stopSpeech, speakingId, supported: speechSupported } = useSpeech();
const autoSpeak = ref(localStorage.getItem("cet6-auto-speak") !== "off");
const toggleAutoSpeak = () => {
  autoSpeak.value = !autoSpeak.value;
  localStorage.setItem("cet6-auto-speak", autoSpeak.value ? "on" : "off");
  if (!autoSpeak.value) stopSpeech();
};
const speakWord = () => speak(current.value?.lemma, { id: "word" });

watch(current, (card) => {
  if (card && autoSpeak.value && !loading.value) {
    speak(card.lemma, { id: "word" });
  }
});

// 翻转三阶段：正面 → 背面（隐藏释义/翻译）→ 背面（完全显示）→ 回正面
const flipCard = () => {
  if (!flipped.value) {
    flipped.value = true;
    revealed.value = false;
  } else if (!revealed.value) {
    revealed.value = true;
  } else {
    flipped.value = false;
    revealed.value = false;
  }
};

const handleTimeUp = () => {
  stopTimer();
  store.notify("学习时间到，学习进度已保存");
  router.push(`/documents/${documentId}`);
};

watch(finished, (done) => {
  if (done) stopTimer();
});

const translateCurrentExamples = async () => {
  if (!untranslatedExamples.value.length || translatingExamples.value) return;
  translatingExamples.value = true;
  try {
    const result = await api.post("/api/translate", {
      sentence_ids: untranslatedExamples.value.map((example) => example.id),
    });
    const translations = Object.fromEntries(
      result.map((item) => [item.sentence_id, item.translation]),
    );
    queue.value.forEach((card) => {
      card.examples = card.examples.map((example) => ({
        ...example,
        translation: translations[example.id] || example.translation,
      }));
    });
    store.notify("当前卡片例句已翻译");
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    translatingExamples.value = false;
  }
};

const answer = async (known) => {
  if (!current.value || answering.value) return;
  answering.value = true;
  const card = current.value;
  try {
    const result = await api.post("/api/reviews", {
      question_set_id: documentId,
      lemma: card.lemma,
      pos: card.pos,
      known,
    });
    if (!card.isRepeat) {
      if (known) knownCount.value += 1;
      else unknownCount.value += 1;
    }
    if (!known) {
      const repeat = { ...card, isRepeat: true, repeatCount: (card.repeatCount || 0) + 1 };
      const gap = repeat.repeatCount === 1 ? 5 : 15;
      queue.value.splice(Math.min(currentIndex.value + gap + 1, queue.value.length), 0, repeat);
    }
    card.status = result.status;
    card.review_count = (card.review_count || 0) + 1;
    currentIndex.value += 1;
    flipped.value = false;
    revealed.value = false;
    resetAI();
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    answering.value = false;
  }
};

const restartUnknown = () => {
  queue.value = queue.value.filter((card) => card.status !== "mastered").map((card) => ({ ...card, isRepeat: false }));
  currentIndex.value = 0;
  knownCount.value = 0;
  unknownCount.value = 0;
  flipped.value = false;
  revealed.value = false;
  resetAI();
};

// 卡片 AI 助手：长难句分析 + 帮助记单词 + 自由提问
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});
const aiQuestion = ref("");
const aiReply = ref("");
const aiLoading = ref(false);
const renderedAiReply = computed(() =>
  aiReply.value ? markdown.render(aiReply.value) : "",
);

const resetAI = () => {
  aiQuestion.value = "";
  aiReply.value = "";
};

const askAI = async (message) => {
  if (aiLoading.value || !current.value) return;
  aiLoading.value = true;
  try {
    const result = await api.post("/api/chat", {
      message,
      question_set_id: documentId,
    });
    aiReply.value = result.reply;
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    aiLoading.value = false;
  }
};

const analyzeExample = (example) =>
  askAI(
    `分析这个句子，按以下三部分输出，用 markdown：\n` +
      "**1. 核心词汇与短语**：逐行列出句中的重点词汇/短语，标注词性与中文释义，并简要点出它在句中的含义或作用。\n" +
      "**2. 句法结构分析**：先指出整句结构（并列/复合/主从等），再逐个分句拆解：主语、谓语、宾语/表语、各类修饰成分（后置定语、状语、从句等），从句需指明引导词及其在句中的作用，代词需指明指代对象。\n" +
      "**3. 参考译文**：给出流畅自然的中文翻译。\n\n" +
      `句子：${example.text}`,
  );

const helpMemorize = () => {
  const card = current.value;
  if (!card) return;
  const context = (card.examples || []).map((ex, i) => `${i + 1}. ${ex.text}`).join("\n");
  askAI(
    `帮我记住英语单词「${card.lemma}」（${card.pos_label || card.pos}），250 字以内，格式如下：\n` +
      "**词义**：一句话\n**记法**：词根词缀拆解或联想记忆，选更管用的\n**搭配**：3 个考试高频搭配\n**易混**：2 个近形/近义词，各一句话辨析\n" +
      (context ? `\n原文语境：\n${context}` : "") +
      "\n\n直接输出内容，不要开场白。",
  );
};

const filterSummary = computed(() => {
  const parts = [];
  if (scope !== "study") parts.push("全文");
  if (statusFilter !== "all") {
    parts.push({ new: "未学习", learning: "学习中", mastered: "已掌握", suspended: "已忽略" }[statusFilter] || "");
  }
  if (minFrequency > 0) parts.push(`出现≥${minFrequency}次`);
  if (reviewFilter !== "all") {
    parts.push({ none: "未复习", min1: "复习≥1次", min3: "复习≥3次", min5: "复习≥5次" }[reviewFilter] || "");
  }
  if (searchFilter) parts.push(`"${searchFilter}"`);
  return parts.join(" · ");
});

onMounted(async () => {
  try {
    const params = new URLSearchParams({
      level,
      order,
      mode,
      scope,
      status: statusFilter,
      search: searchFilter,
      min_frequency: String(minFrequency),
      review_filter: reviewFilter,
    });
    [document.value, queue.value] = await Promise.all([
      api.get(`/api/question-sets/${documentId}`),
      api.get(`/api/question-sets/${documentId}/study-queue?${params}`),
    ]);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
  if (durationMinutes > 0) {
    timerId = window.setInterval(() => {
      remainingSeconds.value -= 1;
      if (remainingSeconds.value <= 0) handleTimeUp();
    }, 1000);
  }
});

onUnmounted(() => {
  stopTimer();
  stopSpeech();
});
</script>

<template>
  <div class="study-page">
    <header class="study-header">
      <RouterLink :to="`/documents/${documentId}`" class="back-link"><ArrowLeft :size="16" /> 退出学习</RouterLink>
      <div class="study-title">
        <strong>{{ document?.title || "真题词汇" }}</strong>
        <span>
          {{ level === "cet6" ? "六级新增词" : level === "cet4" ? "四级基础词" : "四级＋六级" }}
          <em v-if="filterSummary" class="filter-summary">筛选：{{ filterSummary }}</em>
        </span>
      </div>
      <div class="study-score">
        <button
          v-if="speechSupported"
          class="study-speak-toggle"
          :class="{ on: autoSpeak }"
          :title="autoSpeak ? '自动朗读单词：开' : '自动朗读单词：关'"
          @click="toggleAutoSpeak"
        >
          <Volume2 v-if="autoSpeak" :size="13" />
          <VolumeX v-else :size="13" />
          {{ autoSpeak ? "自动朗读" : "静音" }}
        </button>
        <span v-if="durationMinutes > 0" class="study-timer" :class="{ warning: remainingSeconds <= 60 }">
          <Timer :size="13" /> {{ formattedTime }}
        </span>
        <span>{{ knownCount }} 认识</span>
        <span>{{ unknownCount }} 待复习</span>
      </div>
    </header>

    <div class="study-progress"><span :style="{ width: `${progress}%` }"></span></div>

    <main class="study-stage">
      <div v-if="loading" class="loading-panel light"><LoaderCircle class="spin" /> 正在准备卡片</div>

      <section v-else-if="finished" class="session-summary">
        <div class="summary-mark"><Brain :size="34" /></div>
        <p class="eyebrow">SESSION COMPLETE</p>
        <h1 v-if="mode === 'daily' && !queue.length">今日任务已全部完成。</h1>
        <h1 v-else-if="!queue.length">当前筛选下没有可学习的词汇。</h1>
        <h1 v-else>今天这组词，已经走过一遍。</h1>
        <p>"认识"每天最多计一次，跨天累计 3 次后成为已掌握；已学单词将按 1/2/4/7/15/30 天的记忆曲线安排复习。</p>
        <div class="summary-numbers">
          <div><strong>{{ knownCount }}</strong><span>认识</span></div>
          <div><strong>{{ unknownCount }}</strong><span>仍需巩固</span></div>
          <div><strong>{{ queue.length - originalCount }}</strong><span>穿插复现</span></div>
        </div>
        <div class="summary-actions">
          <button class="button secondary" @click="restartUnknown"><RotateCcw :size="17" /> 再学未掌握</button>
          <RouterLink class="button primary" :to="`/documents/${documentId}`">返回词频表</RouterLink>
        </div>
      </section>

      <template v-else-if="current">
        <div class="card-counter">
          <span>{{ currentIndex + 1 }} / {{ queue.length }}</span>
          <span v-if="current.isRepeat" class="repeat-label"><RotateCcw :size="13" /> 穿插复习</span>
        </div>

        <div
          class="flashcard"
          :class="{ flipped }"
          role="button"
          tabindex="0"
          :aria-label="!flipped ? '查看词义与语境' : revealed ? '返回单词面' : '显示释义与翻译'"
          @click="flipCard"
          @keydown.enter="flipCard"
          @keydown.space.prevent="flipCard"
        >
          <div class="flashcard-inner">
            <section class="flashcard-face front">
              <span class="card-level">{{ current.levels.includes("cet6") ? "CET-6" : "CET-4" }}</span>
              <div class="front-word-row">
                <h1>{{ current.lemma }}</h1>
                <button
                  v-if="speechSupported"
                  class="speak-button"
                  :class="{ active: speakingId === 'word' }"
                  aria-label="朗读单词"
                  @click.stop="speakWord"
                  @keydown.stop
                >
                  <Volume2 :size="18" />
                </button>
              </div>
              <p v-if="current.phonetic">/{{ current.phonetic.split('|')[0] }}/</p>
              <span class="flip-hint"><Sparkles :size="15" /> 点击查看词义与语境</span>
            </section>
            <section class="flashcard-face back">
              <header>
                <div>
                  <h2>{{ current.lemma }}</h2>
                  <button
                    v-if="speechSupported"
                    class="speak-button small"
                    :class="{ active: speakingId === 'word' }"
                    aria-label="朗读单词"
                    @click.stop="speakWord"
                    @keydown.stop
                  >
                    <Volume2 :size="15" />
                  </button>
                  <span class="pos-chip">{{ current.pos_label || current.pos }}</span>
                </div>
                <p v-if="revealed">{{ current.definition || "暂无释义" }}</p>
                <p v-else class="definition-masked">先回忆词义，再点一次卡片显示释义与翻译</p>
                <p class="card-review-count">本单词已复习 {{ current.review_count || 0 }} 次</p>
              </header>
              <div class="card-example-toolbar">
                <span>原文语境</span>
                <button
                  v-if="untranslatedExamples.length"
                  class="card-translate-button"
                  :disabled="translatingExamples"
                  @click.stop="translateCurrentExamples"
                  @keydown.stop
                >
                  <LoaderCircle v-if="translatingExamples" class="spin" :size="13" />
                  <Sparkles v-else :size="13" />
                  {{ translatingExamples ? "正在翻译" : `翻译未译例句（${untranslatedExamples.length}）` }}
                </button>
                <span v-else class="card-translated"><Check :size="13" /> 例句已有翻译</span>
              </div>
              <div class="card-examples">
                <article v-for="example in current.examples" :key="example.id">
                  <div class="example-row">
                    <p>{{ example.text }}</p>
                    <div class="example-actions">
                      <button
                        v-if="speechSupported"
                        class="speak-button small"
                        :class="{ active: speakingId === `ex-${example.id}` }"
                        aria-label="朗读例句"
                        @click.stop="speak(example.text, { id: `ex-${example.id}`, rate: 0.9 })"
                        @keydown.stop
                      >
                        <Volume2 :size="13" />
                      </button>
                      <button
                        class="speak-button small analyze"
                        :class="{ active: aiLoading }"
                        :disabled="aiLoading"
                        title="AI 分析这个长难句"
                        aria-label="AI 分析这个长难句"
                        @click.stop="analyzeExample(example)"
                        @keydown.stop
                      >
                        <Bot :size="13" />
                      </button>
                    </div>
                  </div>
                  <small v-if="revealed && example.translation">{{ example.translation }}</small>
                  <small v-else-if="revealed" class="translation-pending">尚未翻译</small>
                </article>
              </div>

              <div class="card-ai-helper" @click.stop>
                <div class="ai-quick-row">
                  <button
                    class="card-translate-button ai-memo-button"
                    :disabled="aiLoading"
                    @click="helpMemorize"
                    @keydown.stop
                  >
                    <LoaderCircle v-if="aiLoading" class="spin" :size="13" />
                    <Bot v-else :size="13" />
                    帮我记住它
                  </button>
                  <form class="ai-ask-form" @submit.prevent="aiQuestion.trim() && askAI(aiQuestion)">
                    <input
                      v-model="aiQuestion"
                      placeholder="补充提问…"
                      :disabled="aiLoading"
                      maxlength="400"
                      @keydown.stop
                    />
                    <button type="submit" :disabled="aiLoading || !aiQuestion.trim()" aria-label="发送问题">
                      <LoaderCircle v-if="aiLoading" class="spin" :size="15" />
                      <MessageCircle v-else :size="15" />
                    </button>
                  </form>
                </div>
                <div v-if="aiLoading && !aiReply" class="ai-loading-hint">
                  <LoaderCircle class="spin" :size="13" /> AI 思考中…
                </div>
                <div
                  v-else-if="aiReply"
                  class="card-ai-reply markdown-content"
                  aria-live="polite"
                  v-html="renderedAiReply"
                ></div>
              </div>
            </section>
          </div>
        </div>

        <div class="study-actions">
          <button class="answer-button unknown" :disabled="answering" @click="answer(false)">
            <X :size="21" /><span><strong>不认识</strong><small>稍后穿插出现</small></span>
          </button>
          <button class="answer-button known" :disabled="answering" @click="answer(true)">
            <Check :size="21" /><span><strong>认识</strong><small>每天计 1 次，满 3 次掌握</small></span>
          </button>
        </div>
      </template>
    </main>
  </div>
</template>
