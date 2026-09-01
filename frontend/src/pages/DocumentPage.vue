<script setup>
import {
  ArrowLeft,
  BookMarked,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSearch,
  Layers3,
  LoaderCircle,
  MessageCircle,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-vue-next";
import MarkdownIt from "markdown-it";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const route = useRoute();
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
const selected = ref(null);
const detailLoading = ref(false);
const translating = ref(false);
const blocks = ref([]);
const blocksLoading = ref(false);
const chatQuestion = ref("");
const chatReply = ref("");
const chatting = ref(false);
const statusUpdating = ref(new Set());
let searchTimer;

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});

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
const renderedChatReply = computed(() =>
  chatReply.value ? markdown.render(chatReply.value) : "",
);

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
  chatReply.value = "";
  try {
    const result = await api.get(`/api/word-stats/${word.id}/examples`);
    selected.value = { word: { ...word, ...result.word }, examples: result.examples };
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    detailLoading.value = false;
  }
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

const askAI = async () => {
  if (!chatQuestion.value.trim() || !selected.value?.examples.length) return;
  chatting.value = true;
  try {
    const result = await api.post("/api/chat", {
      message: chatQuestion.value,
      question_set_id: Number(documentId),
      sentence_id: selected.value.examples[0].id,
    });
    chatReply.value = result.reply;
    chatQuestion.value = "";
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    chatting.value = false;
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

watch([scope, level, status], resetPageAndLoadWords);
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
          <RouterLink class="button primary" :to="`/documents/${document.id}/study?level=${level}`">
            <BookMarked :size="17" /> 开始学习
          </RouterLink>
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
      <div v-if="selected" class="drawer-backdrop" @click.self="selected = null">
        <aside class="word-drawer">
          <button class="drawer-close" @click="selected = null"><X :size="20" /></button>
          <div class="drawer-word">
            <p class="eyebrow">CONTEXT CARD</p>
            <h2>{{ selected.word.lemma }}</h2>
            <p class="phonetic" v-if="selected.word.phonetic">/{{ selected.word.phonetic.split('|')[0] }}/</p>
            <div class="word-meta"><span class="pos-chip">{{ selected.word.pos_label || selected.word.pos }}</span>{{ selected.word.definition }}</div>
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
              </div>
              <p>{{ example.text }}</p>
              <p v-if="example.translation" class="translation">{{ example.translation }}</p>
              <p v-else class="translation pending">尚未翻译</p>
            </article>
          </div>

          <div class="ask-panel">
            <div class="ask-title"><Bot :size="18" /><strong>问 AI</strong><span>结合当前语境</span></div>
            <form @submit.prevent="askAI">
              <textarea v-model="chatQuestion" rows="2" placeholder="例如：这里为什么使用过去分词？"></textarea>
              <button :disabled="chatting || !chatQuestion.trim()" aria-label="发送问题">
                <LoaderCircle v-if="chatting" class="spin" :size="17" />
                <MessageCircle v-else :size="17" />
              </button>
            </form>
            <div
              v-if="chatReply"
              class="ai-reply markdown-content"
              aria-live="polite"
              v-html="renderedChatReply"
            ></div>
          </div>
        </aside>
      </div>
    </Transition>
  </div>
</template>
