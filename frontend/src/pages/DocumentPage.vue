<script setup>
import {
  ArrowLeft,
  BookMarked,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSearch,
  Layers3,
  LoaderCircle,
  Search,
  SlidersHorizontal,
  Sparkles,
  Volume2,
  X,
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api";
import { useSpeech } from "../composables/useSpeech";
import { useAppStore } from "../stores/app";

const route = useRoute();
const router = useRouter();
const store = useAppStore();
const documentId = route.params.id;
const document = ref(null);
const words = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 200;
const loading = ref(true);
const activeTab = ref("words");
const search = ref("");
const scope = ref("study");
const level = ref("cet6");
const status = ref("all");
const minFrequency = ref(0);
const reviewFilter = ref("all");
const selected = ref(null);
const detailLoading = ref(false);
const translating = ref(false);
const blocks = ref([]);
const blocksLoading = ref(false);
const statusUpdating = ref(new Set());
let searchTimer;

const studyDialogOpen = ref(false);
const studyMode = ref("daily");
const studyOrder = ref("frequency");
const studyDuration = ref(20);
const customDuration = ref("");
const durationPresets = [0, 15, 20, 30, 45, 60];

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

const includedBlocks = computed(() => blocks.value.filter((block) => block.is_included).length);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const pageStart = computed(() => (total.value ? (page.value - 1) * pageSize + 1 : 0));
const pageEnd = computed(() => Math.min(page.value * pageSize, total.value));
const filterSummary = computed(() => {
  const parts = [];
  parts.push(scope.value === "study" ? "学习范围" : "全文");
  parts.push({ cet6: "六级新增", cet4: "四级基础", all: "四级＋六级" }[level.value] || "六级新增");
  if (status.value !== "all") {
    parts.push({ new: "未学习", learning: "学习中", mastered: "已掌握", suspended: "已忽略" }[status.value]);
  }
  if (minFrequency.value > 0) parts.push(`出现≥${minFrequency.value}次`);
  if (reviewFilter.value !== "all") {
    parts.push({ none: "未复习", min1: "复习≥1次", min3: "复习≥3次", min5: "复习≥5次" }[reviewFilter.value]);
  }
  if (search.value.trim()) parts.push(`搜索"${search.value.trim()}"`);
  return parts.join(" · ");
});

const loadDocument = async () => {
  document.value = await api.get(`/api/question-sets/${documentId}`);
};

const loadWords = async () => {
  loading.value = true;
  const params = new URLSearchParams({
    scope: scope.value,
    level: level.value,
    status: status.value,
    search: search.value,
    min_frequency: String(minFrequency.value),
    review_filter: reviewFilter.value,
    page: String(page.value),
    page_size: String(pageSize),
  });
  try {
    const result = await api.get(`/api/question-sets/${documentId}/word-stats?${params}`);
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

const startStudy = () => {
  let duration = studyDuration.value;
  if (duration === -1) {
    const parsed = Number(customDuration.value);
    if (!Number.isFinite(parsed) || parsed < 1 || parsed > 240) {
      store.notify("请输入 1–240 之间的分钟数", "error");
      return;
    }
    duration = Math.floor(parsed);
  }
  const params = new URLSearchParams({
    level: level.value,
    mode: studyMode.value,
    order: studyOrder.value,
    duration: String(duration),
    scope: scope.value,
    status: status.value,
    min_frequency: String(minFrequency.value),
    review_filter: reviewFilter.value,
    search: search.value,
  });
  studyDialogOpen.value = false;
  router.push(`/documents/${documentId}/study?${params}`);
};

const loadBlocks = async () => {
  if (blocks.value.length) return;
  blocksLoading.value = true;
  try {
    blocks.value = await api.get(`/api/question-sets/${documentId}/blocks`);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    blocksLoading.value = false;
  }
};

const openWord = async (word) => {
  selected.value = { word, examples: [] };
  detailLoading.value = true;
  try {
    const result = await api.get(`/api/word-stats/${word.id}/examples`);
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
  try {
    const posValues = word.pos_values?.length ? word.pos_values : [word.pos];
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
    if (document.value) {
      if (previousStatus !== "mastered" && nextStatus === "mastered") {
        document.value.mastered_count += 1;
      } else if (previousStatus === "mastered" && nextStatus !== "mastered") {
        document.value.mastered_count = Math.max(0, document.value.mastered_count - 1);
      }
    }
    if (status.value !== "all" && status.value !== nextStatus) {
      words.value = words.value.filter(
        (item) => item.lemma !== word.lemma,
      );
      total.value = Math.max(0, total.value - 1);
    }
    store.notify(nextStatus === "mastered" ? "已标记为掌握" : "状态已更新");
    return true;
  } catch (error) {
    store.notify(error.message, "error");
    return false;
  }
};

const markMasteredFromTable = async (word) => {
  if (word.status === "mastered" || statusUpdating.value.has(word.id)) return;
  statusUpdating.value = new Set(statusUpdating.value).add(word.id);
  try {
    await setStatus(word, "mastered");
  } finally {
    const next = new Set(statusUpdating.value);
    next.delete(word.id);
    statusUpdating.value = next;
  }
};

const toggleBlock = async (block) => {
  const previous = block.is_included;
  block.is_included = !previous;
  try {
    await api.patch(`/api/blocks/${block.id}`, { is_included: block.is_included });
    await loadWords();
  } catch (error) {
    block.is_included = previous;
    store.notify(error.message, "error");
  }
};

const resetPageAndLoadWords = () => {
  if (page.value === 1) loadWords();
  else page.value = 1;
};

watch([scope, level, status, minFrequency, reviewFilter], resetPageAndLoadWords);
watch(page, loadWords);
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(resetPageAndLoadWords, 250);
});
watch(activeTab, (tab) => tab === "preview" && loadBlocks());

onMounted(async () => {
  try {
    await Promise.all([loadDocument(), loadWords()]);
  } catch (error) {
    store.notify(error.message, "error");
  }
});
</script>

<template>
  <div class="page document-page">
    <header v-if="document" class="document-header">
      <RouterLink class="back-link" to="/"><ArrowLeft :size="16" /> 返回题库</RouterLink>
      <div class="document-hero">
        <div>
          <p class="eyebrow">PAPER WORKSPACE</p>
          <h1>{{ document.title }}</h1>
          <p>
            {{ document.page_count }} 页 · {{ document.word_count.toLocaleString() }} 个英文词 ·
            解析器 {{ document.parser_version }}
          </p>
        </div>
        <div class="hero-actions">
          <a class="button secondary" :href="`/api/export/${document.id}`">
            <Download :size="17" /> 导出 Excel
          </a>
          <button class="button primary" @click="studyDialogOpen = true">
            <BookMarked :size="17" /> 开始学习
          </button>
        </div>
      </div>
      <div class="document-kpis">
        <div><strong>{{ total }}</strong><span>筛选结果总词条</span></div>
        <div><strong>{{ document.block_counts.passage || 0 }}</strong><span>正文区块</span></div>
        <div><strong>{{ document.mastered_count }}</strong><span>已掌握</span></div>
        <div><strong>{{ document.block_counts.boilerplate || 0 }}</strong><span>已识别页眉页脚</span></div>
      </div>
    </header>

    <div class="workspace-tabs">
      <button :class="{ active: activeTab === 'words' }" @click="activeTab = 'words'">
        <Layers3 :size="17" /> 词频表
      </button>
      <button :class="{ active: activeTab === 'preview' }" @click="activeTab = 'preview'">
        <FileSearch :size="17" /> 导入预览
      </button>
    </div>

    <section v-if="activeTab === 'words'" class="workspace-card">
      <div class="toolbar">
        <label class="search-field">
          <Search :size="17" />
          <input v-model="search" placeholder="搜索单词或中文释义" />
        </label>
        <div class="segmented-control">
          <button :class="{ active: scope === 'study' }" @click="scope = 'study'">学习范围</button>
          <button :class="{ active: scope === 'all' }" @click="scope = 'all'">全文</button>
        </div>
        <label class="select-field">
          <span>词库</span>
          <select v-model="level">
            <option value="cet6">六级新增</option>
            <option value="cet4">四级基础</option>
            <option value="all">四级＋六级</option>
          </select>
          <ChevronDown :size="15" />
        </label>
        <label class="select-field">
          <span>状态</span>
          <select v-model="status">
            <option value="all">全部</option>
            <option value="new">未学习</option>
            <option value="learning">学习中</option>
            <option value="mastered">已掌握</option>
            <option value="suspended">已忽略</option>
          </select>
          <ChevronDown :size="15" />
        </label>
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

      <div v-if="loading" class="loading-panel"><LoaderCircle class="spin" :size="23" /> 正在统计词频</div>
      <div v-else-if="!words.length" class="empty-state compact-empty">
        <Search :size="30" />
        <h3>当前筛选下没有词条</h3>
        <p>可切换到“全文”或“四级＋六级”查看更大范围。</p>
      </div>
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
          <table class="word-table">
          <thead>
            <tr>
              <th>词汇</th>
              <th>词性</th>
              <th>释义</th>
              <th class="numeric">出现</th>
              <th class="numeric">正文</th>
              <th class="numeric">复习</th>
              <th>掌握状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="word in words" :key="word.id" @click="openWord(word)">
              <td>
                <strong class="word-name">{{ word.lemma }}</strong>
                <small v-if="word.phonetic">/{{ word.phonetic.split('|')[0] }}/</small>
              </td>
              <td><span class="pos-chip">{{ word.pos_label || word.pos }}</span></td>
              <td class="definition-cell">{{ word.definition || "暂无释义" }}</td>
              <td class="numeric frequency-cell">{{ word.frequency }}</td>
              <td class="numeric">{{ word.passage_frequency }}</td>
              <td class="numeric review-count-cell" :class="{ zero: !word.review_count }">
                {{ word.review_count || 0 }}
              </td>
              <td>
                <button
                  class="mastery-pill mastery-button"
                  :class="word.status"
                  :disabled="statusUpdating.has(word.id)"
                  :aria-label="
                    word.status === 'mastered'
                      ? `${word.lemma} 已掌握`
                      : `将 ${word.lemma} 标记为已掌握`
                  "
                  :title="word.status === 'mastered' ? '已掌握' : '点击标记为已掌握'"
                  @click.stop="markMasteredFromTable(word)"
                >
                  <LoaderCircle v-if="statusUpdating.has(word.id)" class="spin" :size="11" />
                  <Check v-else-if="word.status === 'mastered'" :size="11" />
                  {{
                    { new: "未学习", learning: "学习中", mastered: "已掌握", suspended: "已忽略" }[
                      word.status
                    ]
                  }}
                </button>
              </td>
              <td><span class="table-link">查看语境</span></td>
            </tr>
          </tbody>
          </table>
        </div>
      </div>
    </section>

    <section v-else class="preview-layout">
      <div class="preview-guide">
        <SlidersHorizontal :size="21" />
        <div>
          <h3>校准学习范围</h3>
          <p>解析器默认纳入正文、题干、写作和翻译；固定说明、选项和页眉页脚默认排除。</p>
        </div>
        <strong>{{ includedBlocks }} / {{ blocks.length }} 个区块纳入统计</strong>
      </div>
      <div v-if="blocksLoading" class="loading-panel"><LoaderCircle class="spin" /> 正在读取页面结构</div>
      <div v-else class="block-list">
        <article v-for="block in blocks" :key="block.id" class="content-block" :class="{ excluded: !block.is_included }">
          <header>
            <div>
              <span class="page-chip">P.{{ block.page }}</span>
              <span class="type-chip" :class="block.content_type">{{ typeLabels[block.content_type] }}</span>
              <span class="section-label">{{ block.section_name }}</span>
            </div>
            <button class="include-toggle" :class="{ active: block.is_included }" @click="toggleBlock(block)">
              <Check v-if="block.is_included" :size="14" />
              {{ block.is_included ? "纳入" : "排除" }}
            </button>
          </header>
          <p>{{ block.text }}</p>
        </article>
      </div>
    </section>

    <Transition name="drawer">
      <div v-if="selected" class="drawer-backdrop" @click.self="closeWordDrawer">
        <aside class="word-drawer">
          <button class="drawer-close" @click="closeWordDrawer"><X :size="20" /></button>
          <div class="drawer-word">
            <p class="eyebrow">CONTEXT CARD</p>
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
            <h3>原文语境 <span>{{ selected.examples.length }}</span></h3>
            <article v-for="example in selected.examples" :key="example.id" class="example-card">
              <div class="example-labels">
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

    <Transition name="drawer">
      <div v-if="studyDialogOpen" class="modal-backdrop" @click.self="studyDialogOpen = false">
        <div class="study-setup-modal" role="dialog" aria-label="学习设置">
          <header>
            <div>
              <p class="eyebrow">STUDY SETUP</p>
              <h2>开始学习</h2>
            </div>
            <button class="drawer-close" aria-label="关闭" @click="studyDialogOpen = false">
              <X :size="18" />
            </button>
          </header>

          <p class="study-scope-line">
            <SlidersHorizontal :size="14" />
            学习范围：{{ filterSummary }} · 共 {{ total }} 词条
            <small v-if="status === 'all'">（已掌握与已忽略不会进入学习）</small>
          </p>

          <section>
            <h3>学习模式</h3>
            <div class="option-grid">
              <label class="option-card" :class="{ active: studyMode === 'daily' }">
                <input v-model="studyMode" type="radio" value="daily" />
                <strong>每日任务</strong>
                <small>筛选范围内的到期复习词 + 最多 20 个新词</small>
              </label>
              <label class="option-card" :class="{ active: studyMode === 'free' }">
                <input v-model="studyMode" type="radio" value="free" />
                <strong>自由学习</strong>
                <small>筛选范围内可学习的词汇，一口气过完</small>
              </label>
            </div>
          </section>

          <section>
            <h3>学习顺序<span>每日任务模式下应用于新词部分</span></h3>
            <div class="option-grid">
              <label class="option-card" :class="{ active: studyOrder === 'frequency' }">
                <input v-model="studyOrder" type="radio" value="frequency" />
                <strong>按出现频率</strong>
                <small>高频词优先，先抓重点</small>
              </label>
              <label class="option-card" :class="{ active: studyOrder === 'review_count' }">
                <input v-model="studyOrder" type="radio" value="review_count" />
                <strong>按复习次数</strong>
                <small>复习次数多的优先，集中攻坚薄弱词</small>
              </label>
            </div>
          </section>

          <section>
            <h3>学习时长<span>到时自动退出并保存学习进度</span></h3>
            <div class="duration-pills">
              <button
                v-for="preset in durationPresets"
                :key="preset"
                :class="{ active: studyDuration === preset }"
                type="button"
                @click="studyDuration = preset"
              >
                {{ preset === 0 ? "不限时" : `${preset} 分钟` }}
              </button>
              <button
                :class="{ active: studyDuration === -1 }"
                type="button"
                @click="studyDuration = -1"
              >
                自定义
              </button>
            </div>
            <div v-if="studyDuration === -1" class="custom-duration">
              <input
                v-model="customDuration"
                type="number"
                min="1"
                max="240"
                placeholder="1–240"
                aria-label="自定义学习分钟数"
              />
              <span>分钟</span>
            </div>
          </section>

          <footer>
            <button class="button secondary" type="button" @click="studyDialogOpen = false">取消</button>
            <button class="button primary" type="button" @click="startStudy">
              <BookMarked :size="16" /> 开始学习
            </button>
          </footer>
        </div>
      </div>
    </Transition>
  </div>
</template>
