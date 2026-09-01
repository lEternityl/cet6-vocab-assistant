<script setup>
import {
  ArrowLeft,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const route = useRoute();
const store = useAppStore();
const documentId = Number(route.params.id);
const level = route.query.level || "cet6";
const document = ref(null);
const queue = ref([]);
const currentIndex = ref(0);
const flipped = ref(false);
const loading = ref(true);
const answering = ref(false);
const translatingExamples = ref(false);
const knownCount = ref(0);
const unknownCount = ref(0);

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
    currentIndex.value += 1;
    flipped.value = false;
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
};

onMounted(async () => {
  try {
    [document.value, queue.value] = await Promise.all([
      api.get(`/api/question-sets/${documentId}`),
      api.get(`/api/question-sets/${documentId}/study-queue?level=${level}`),
    ]);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="study-page">
    <header class="study-header">
      <RouterLink :to="`/documents/${documentId}`" class="back-link"><ArrowLeft :size="16" /> 退出学习</RouterLink>
      <div class="study-title">
        <strong>{{ document?.title || "真题词汇" }}</strong>
        <span>{{ level === "cet6" ? "六级新增词" : level === "cet4" ? "四级基础词" : "四级＋六级" }}</span>
      </div>
      <div class="study-score"><span>{{ knownCount }} 认识</span><span>{{ unknownCount }} 待复习</span></div>
    </header>

    <div class="study-progress"><span :style="{ width: `${progress}%` }"></span></div>

    <main class="study-stage">
      <div v-if="loading" class="loading-panel light"><LoaderCircle class="spin" /> 正在准备卡片</div>

      <section v-else-if="finished" class="session-summary">
        <div class="summary-mark"><Brain :size="34" /></div>
        <p class="eyebrow">SESSION COMPLETE</p>
        <h1>今天这组词，已经走过一遍。</h1>
        <p>“认识”会先进入学习中，跨次累计 3 次后才会成为已掌握。</p>
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
          :aria-label="flipped ? '返回单词面' : '查看词义与语境'"
          @click="flipped = !flipped"
          @keydown.enter="flipped = !flipped"
          @keydown.space.prevent="flipped = !flipped"
        >
          <div class="flashcard-inner">
            <section class="flashcard-face front">
              <span class="card-level">{{ current.levels.includes("cet6") ? "CET-6" : "CET-4" }}</span>
              <h1>{{ current.lemma }}</h1>
              <p v-if="current.phonetic">/{{ current.phonetic.split('|')[0] }}/</p>
              <span class="flip-hint"><Sparkles :size="15" /> 点击查看词义与语境</span>
            </section>
            <section class="flashcard-face back">
              <header>
                <div><h2>{{ current.lemma }}</h2><span class="pos-chip">{{ current.pos_label || current.pos }}</span></div>
                <p>{{ current.definition || "暂无释义" }}</p>
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
                  <p>{{ example.text }}</p>
                  <small v-if="example.translation">{{ example.translation }}</small>
                  <small v-else class="translation-pending">尚未翻译</small>
                </article>
              </div>
              <span class="flip-hint">点击返回单词面</span>
            </section>
          </div>
        </div>

        <div class="study-actions">
          <button class="answer-button unknown" :disabled="answering" @click="answer(false)">
            <X :size="21" /><span><strong>不认识</strong><small>稍后穿插出现</small></span>
          </button>
          <button class="answer-button known" :disabled="answering" @click="answer(true)">
            <Check :size="21" /><span><strong>认识</strong><small>累计 3 次才掌握</small></span>
          </button>
        </div>
      </template>
    </main>
  </div>
</template>
