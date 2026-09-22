<script setup>
import {
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  LibraryBig,
  LoaderCircle,
  Search,
  Sparkles,
  TrendingUp,
  Volume2,
  X,
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import { api } from "../api";
import { useSpeech } from "../composables/useSpeech";
import { useAppStore } from "../stores/app";

const store = useAppStore();
const words = ref([]);
const total = ref(0);
const loading = ref(true);
const level = ref("cet6");
const status = ref("all");
const search = ref("");
const minFrequency = ref(0);
const reviewFilter = ref("all");
const page = ref(1);
const pageSize = 50;
let timer;

const selected = ref(null);
const detailLoading = ref(false);
const translating = ref(false);
const statusUpdating = ref("");

const typeLabels = {
  passage: "阅读正文",
  question: "题干",
  option: "选项",
  instruction: "固定说明",
  boilerplate: "页眉页脚",
  listening: "听力",
  writing: "写作",
  translation: "翻译",
  unknown: "未分类",
};

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const pageStart = computed(() => (total.value ? (page.value - 1) * pageSize + 1 : 0));
const pageEnd = computed(() => Math.min(page.value * pageSize, total.value));

const load = async () => {
  loading.value = true;
  try {
    const params = new URLSearchParams({
      level: level.value,
      status: status.value,
      search: search.value,
      min_frequency: String(minFrequency.value),
      review_filter: reviewFilter.value,
      page: String(page.value),
      page_size: String(pageSize),
    });
    const result = await api.get(`/api/corpus/word-stats?${params}`);
    words.value = result.items;
    total.value = result.total;
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
};

const formatReviewTime = (iso) => {
  if (!iso) return "";
  const date = new Date(/Z$|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "";
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}月${day}日 ${hour}:${minute}`;
};

const openWord = async (word) => {
  selected.value = { word, examples: [] };
  detailLoading.value = true;
  try {
    const result = await api.get(
      `/api/corpus/word-stats/${encodeURIComponent(word.lemma)}/examples`,
    );
    selected.value = { word: { ...word, ...result.word }, examples: result.examples };
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    detailLoading.value = false;
  }
};

// 朗读抽屉中的单词与例句
const { speak, stop: stopSpeech, speakingId, supported: speechSupported } = useSpeech();
const closeWordDrawer = () => {
  stopSpeech();
  selected.value = null;
};

const translateExamples = async () => {
  const pending = selected.value.examples.filter((example) => !example.translation).slice(0, 20);
  if (!pending.length) return;
  translating.value = true;
  try {
    const result = await api.post("/api/translate", {
      sentence_ids: pending.map((example) => example.id),
    });
    const translations = Object.fromEntries(result.map((item) => [item.sentence_id, item.translation]));
    selected.value.examples = selected.value.examples.map((example) => ({
      ...example,
      translation: translations[example.id] || example.translation,
    }));
    store.notify("例句翻译已缓存");
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    translating.value = false;
  }
};

const setStatus = async (word, nextStatus) => {
  const previousStatus = word.status;
  if (previousStatus === nextStatus) return true;
  statusUpdating.value = word.lemma;
  try {
    const posValues = word.pos_values?.length ? word.pos_values : [word.pos || "X"];
    await Promise.all(
      posValues.map((pos) =>
        api.put(
          `/api/vocab/${encodeURIComponent(word.lemma)}/${encodeURIComponent(pos)}`,
          { status: nextStatus },
        ),
      ),
    );
    words.value.forEach((item) => {
      if (item.lemma === word.lemma) item.status = nextStatus;
    });
    if (selected.value?.word.lemma === word.lemma) {
      selected.value.word.status = nextStatus;
    }
    if (status.value !== "all" && status.value !== nextStatus) {
      words.value = words.value.filter((item) => item.lemma !== word.lemma);
      total.value = Math.max(0, total.value - 1);
    }
    store.notify(nextStatus === "mastered" ? "已标记为掌握" : "状态已更新");
    return true;
  } catch (error) {
    store.notify(error.message, "error");
    return false;
  } finally {
    statusUpdating.value = "";
  }
};

const resetPageAndLoad = () => {
  if (page.value === 1) load();
  else page.value = 1;
};

watch([level, status, minFrequency, reviewFilter], resetPageAndLoad);
watch(page, load);
watch(search, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(resetPageAndLoad, 250);
});
onMounted(load);
</script>

<template>
  <div class="page corpus-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">ACROSS ALL PAPERS</p>
        <h1>历年词频，不只看一个数字。</h1>
        <p class="lead">同时比较累计出现次数和覆盖试卷数，优先学习稳定高频词。</p>
      </div>
    </header>

    <section class="corpus-callout">
      <span><TrendingUp :size="23" /></span>
      <div><strong>排序依据：学习范围总词频</strong><p>固定说明、页眉页脚和默认排除的选项不会进入学习范围。</p></div>
      <div class="callout-stat"><strong>{{ total }}</strong><small>当前可见词条</small></div>
    </section>

    <section class="workspace-card">
      <div class="toolbar">
        <label class="search-field"><Search :size="17" /><input v-model="search" placeholder="搜索历年词汇" /></label>
        <label class="select-field"><span>词库</span><select v-model="level"><option value="cet6">六级新增</option><option value="cet4">四级基础</option><option value="all">全部</option></select><ChevronDown :size="15" /></label>
        <label class="select-field"><span>状态</span><select v-model="status"><option value="all">全部</option><option value="new">未学习</option><option value="learning">学习中</option><option value="mastered">已掌握</option><option value="suspended">已忽略</option></select><ChevronDown :size="15" /></label>
        <label class="select-field">
          <span>出现频率</span>
          <select v-model.number="minFrequency">
            <option :value="0">全部</option>
            <option :value="2">≥ 2 次</option>
            <option :value="3">≥ 3 次</option>
            <option :value="5">≥ 5 次</option>
            <option :value="10">≥ 10 次</option>
          </select>
          <ChevronDown :size="15" />
        </label>
        <label class="select-field">
          <span>复习次数</span>
          <select v-model="reviewFilter">
            <option value="all">全部</option>
            <option value="none">未复习</option>
            <option value="min1">≥ 1 次</option>
            <option value="min3">≥ 3 次</option>
            <option value="min5">≥ 5 次</option>
          </select>
          <ChevronDown :size="15" />
        </label>
      </div>
      <div v-if="loading" class="loading-panel"><LoaderCircle class="spin" /> 正在汇总历年词频</div>
      <div v-else-if="!words.length" class="empty-state compact-empty"><LibraryBig :size="32" /><h3>当前筛选下没有词条</h3><p>可切换词库或放宽筛选条件查看更大范围。</p></div>
      <div v-else class="word-results">
        <div class="table-pagination">
          <span>当前显示 {{ pageStart }}–{{ pageEnd }} 条，共 {{ total }} 条</span>
          <div v-if="pageCount > 1" class="pagination-actions">
            <button :disabled="page === 1" @click="page -= 1">
              <ChevronLeft :size="14" /> 上一页
            </button>
            <strong>第 {{ page }} / {{ pageCount }} 页</strong>
            <button :disabled="page >= pageCount" @click="page += 1">
              下一页 <ChevronRight :size="14" />
            </button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="word-table corpus-table">
            <thead><tr><th>#</th><th>词汇</th><th>释义</th><th class="numeric">学习范围</th><th class="numeric">全文</th><th class="numeric">出现试卷</th><th class="numeric">复习</th><th>掌握状态</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(word, index) in words" :key="word.lemma" @click="openWord(word)">
                <td class="rank">{{ pageStart + index }}</td>
                <td><strong class="word-name">{{ word.lemma }}</strong><small>{{ word.pos_label }} · /{{ word.phonetic?.split('|')[0] || '—' }}/</small></td>
                <td class="definition-cell">{{ word.definition }}</td>
                <td class="numeric frequency-cell">{{ word.study_frequency }}</td>
                <td class="numeric">{{ word.total_frequency }}</td>
                <td class="numeric"><span class="document-frequency">{{ word.document_frequency }} 套</span></td>
                <td class="numeric review-count-cell" :class="{ zero: !word.review_count }">{{ word.review_count || 0 }}</td>
                <td>
                  <button
                    class="mastery-pill mastery-button"
                    :class="word.status"
                    :disabled="statusUpdating === word.lemma"
                    :aria-label="
                      word.status === 'mastered'
                        ? `${word.lemma} 已掌握`
                        : `将 ${word.lemma} 标记为已掌握`
                    "
                    :title="word.status === 'mastered' ? '已掌握' : '点击标记为已掌握'"
                    @click.stop="setStatus(word, 'mastered')"
                  >
                    <LoaderCircle v-if="statusUpdating === word.lemma" class="spin" :size="11" />
                    <Check v-else-if="word.status === 'mastered'" :size="11" />
                    {{ { new: '未学习', learning: '学习中', mastered: '已掌握', suspended: '已忽略' }[word.status] }}
                  </button>
                </td>
                <td><span class="table-link">查看语境</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <Transition name="drawer">
      <div v-if="selected" class="drawer-backdrop" @click.self="closeWordDrawer">
        <aside class="word-drawer">
          <button class="drawer-close" @click="closeWordDrawer"><X :size="20" /></button>
          <div class="drawer-word">
            <p class="eyebrow">CONTEXT CARD · ALL PAPERS</p>
            <div class="drawer-word-row">
              <h2>{{ selected.word.lemma }}</h2>
              <button
                v-if="speechSupported"
                class="speak-button"
                :class="{ active: speakingId === 'drawer-word' }"
                aria-label="朗读单词"
                @click="speak(selected.word.lemma, { id: 'drawer-word' })"
              >
                <Volume2 :size="17" />
              </button>
            </div>
            <p class="phonetic" v-if="selected.word.phonetic">/{{ selected.word.phonetic.split('|')[0] }}/</p>
            <div class="word-meta"><span class="pos-chip">{{ selected.word.pos_label || selected.word.pos }}</span>{{ selected.word.definition }}</div>
            <div class="word-review-meta">
              <span class="review-chip">本单词已复习 {{ selected.word.review_count || 0 }} 次</span>
              <span v-if="selected.word.next_review_at" class="review-chip next">
                下次复习 {{ formatReviewTime(selected.word.next_review_at) }}
              </span>
            </div>
            <div class="drawer-actions">
              <button
                class="button small secondary"
                @click="setStatus(selected.word, selected.word.status === 'mastered' ? 'new' : 'mastered')"
              >
                <Check :size="15" /> {{ selected.word.status === "mastered" ? "撤销掌握" : "标记掌握" }}
              </button>
              <button class="button small ghost" :disabled="translating" @click="translateExamples">
                <LoaderCircle v-if="translating" class="spin" :size="15" />
                <Sparkles v-else :size="15" /> 翻译未译例句
              </button>
            </div>
          </div>

          <div v-if="detailLoading" class="loading-panel"><LoaderCircle class="spin" /> 正在查找语境</div>
          <div v-else class="example-list">
            <h3>跨试卷语境 <span>{{ selected.examples.length }}</span></h3>
            <article v-for="example in selected.examples" :key="example.id" class="example-card">
              <div class="example-labels">
                <span v-if="example.question_set_title" class="paper-chip">{{ example.question_set_title }}</span>
                <span>P.{{ example.page }}</span><span>{{ typeLabels[example.content_type] }}</span>
                <button
                  v-if="speechSupported"
                  class="speak-button small"
                  :class="{ active: speakingId === `drawer-ex-${example.id}` }"
                  aria-label="朗读例句"
                  @click="speak(example.text, { id: `drawer-ex-${example.id}`, rate: 0.9 })"
                >
                  <Volume2 :size="13" />
                </button>
              </div>
              <p>{{ example.text }}</p>
              <p v-if="example.translation" class="translation">{{ example.translation }}</p>
              <p v-else class="translation pending">尚未翻译</p>
            </article>
          </div>
        </aside>
      </div>
    </Transition>
  </div>
</template>
