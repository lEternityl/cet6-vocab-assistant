<script setup>
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  LoaderCircle,
  MoreHorizontal,
  RotateCw,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const store = useAppStore();
const overview = ref({});
const documents = ref([]);
const loading = ref(true);
const uploading = ref(false);
const dragging = ref(false);
const fileInput = ref(null);
let pollingTimer;

const activeDocuments = computed(() =>
  documents.value.filter((document) => ["queued", "processing"].includes(document.status)),
);

const load = async (quiet = false) => {
  if (!quiet) loading.value = true;
  try {
    [overview.value, documents.value] = await Promise.all([
      api.get("/api/overview"),
      api.get("/api/question-sets"),
    ]);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
};

const uploadFiles = async (files) => {
  const accepted = [...files].filter((file) => /\.(pdf|docx)$/i.test(file.name));
  if (!accepted.length) {
    store.notify("请选择 PDF 或 DOCX 真题", "error");
    return;
  }
  uploading.value = true;
  try {
    for (const file of accepted) {
      const result = await api.upload(file);
      store.notify(result.duplicate ? `${file.name} 已在题库中` : `${file.name} 已加入解析队列`);
    }
    await load(true);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
};

const removeDocument = async (document) => {
  if (!window.confirm(`确认删除“${document.title}”及其解析记录？`)) return;
  try {
    await api.delete(`/api/question-sets/${document.id}`);
    documents.value = documents.value.filter((item) => item.id !== document.id);
    store.notify("已从题库删除");
  } catch (error) {
    store.notify(error.message, "error");
  }
};

const reprocess = async (document) => {
  try {
    await api.post(`/api/question-sets/${document.id}/reprocess`, {});
    store.notify("已重新加入解析队列");
    await load(true);
  } catch (error) {
    store.notify(error.message, "error");
  }
};

const formatDate = (value) =>
  new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(
    new Date(value),
  );

onMounted(async () => {
  await load();
  pollingTimer = window.setInterval(() => {
    if (activeDocuments.value.length) load(true);
  }, 1800);
});

onBeforeUnmount(() => window.clearInterval(pollingTimer));
</script>

<template>
  <div class="page home-page">
    <header class="page-header home-header">
      <div>
        <p class="eyebrow">YOUR CET-6 FIELD NOTES</p>
        <h1>把一套真题，变成今天的词汇课。</h1>
        <p class="lead">上传试卷，先识别正文与题目结构，再从真实语境中筛出值得学的词。</p>
      </div>
      <button class="button primary desktop-action" @click="fileInput?.click()">
        <UploadCloud :size="18" /> 上传真题
      </button>
    </header>

    <input
      ref="fileInput"
      class="sr-only"
      type="file"
      accept=".pdf,.docx"
      multiple
      @change="uploadFiles($event.target.files)"
    />

    <section
      class="upload-stage"
      :class="{ dragging, busy: uploading }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="dragging = false; uploadFiles($event.dataTransfer.files)"
      @click="!uploading && fileInput?.click()"
    >
      <div class="upload-illustration">
        <LoaderCircle v-if="uploading" class="spin" :size="30" />
        <UploadCloud v-else :size="30" />
      </div>
      <div>
        <h2>{{ uploading ? "正在接收真题…" : "拖入 PDF 或 Word" }}</h2>
        <p>可一次选择多套，重复文件会自动识别。单个文件不超过 50 MB。</p>
      </div>
      <span class="upload-badge">文本型 PDF · DOCX</span>
    </section>

    <section class="metric-grid" aria-label="学习概览">
      <article class="metric-card navy">
        <span class="metric-icon"><FileText :size="19" /></span>
        <p>已收录真题</p>
        <strong>{{ overview.total_documents || 0 }}</strong>
        <small>{{ overview.completed_documents || 0 }} 套解析完成</small>
      </article>
      <article class="metric-card coral">
        <span class="metric-icon"><Clock3 :size="19" /></span>
        <p>正在学习</p>
        <strong>{{ overview.learning || 0 }}</strong>
        <small>等待下一次确认</small>
      </article>
      <article class="metric-card mint">
        <span class="metric-icon"><CheckCircle2 :size="19" /></span>
        <p>已经掌握</p>
        <strong>{{ overview.mastered || 0 }}</strong>
        <small>需连续认识 3 次</small>
      </article>
      <article class="metric-card paper">
        <span class="metric-icon"><Sparkles :size="19" /></span>
        <p>复习判断</p>
        <strong>{{ overview.review_events || 0 }}</strong>
        <small>每次选择都有记录</small>
      </article>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <div>
          <p class="eyebrow">MY PAPERS</p>
          <h2>我的题库</h2>
        </div>
        <span class="quiet-label">按上传时间排序</span>
      </div>

      <div v-if="loading" class="loading-panel">
        <LoaderCircle class="spin" :size="24" /> 正在读取题库
      </div>
      <div v-else-if="!documents.length" class="empty-state">
        <FileText :size="36" />
        <h3>题库还是空的</h3>
        <p>从上方上传一套真题，解析完成后就能查看词频和开始学习。</p>
      </div>
      <div v-else class="document-list">
        <article v-for="document in documents" :key="document.id" class="document-row">
          <div class="file-monogram" :class="document.status">
            <LoaderCircle v-if="document.status === 'processing'" class="spin" :size="22" />
            <FileText v-else :size="22" />
          </div>
          <div class="document-main">
            <div class="document-title-line">
              <h3>{{ document.title }}</h3>
              <span class="status-pill" :class="document.status">
                {{
                  document.status === "done"
                    ? "可学习"
                    : document.status === "error"
                      ? "解析失败"
                      : document.current_phase
                }}
              </span>
            </div>
            <p>
              {{ formatDate(document.created_at) }}
              <template v-if="document.status === 'done'">
                · {{ document.page_count }} 页 · {{ document.vocab_count }} 个词条
              </template>
            </p>
            <div v-if="['queued', 'processing'].includes(document.status)" class="progress-track">
              <span :style="{ width: `${document.progress}%` }"></span>
            </div>
            <p v-if="document.status === 'error'" class="error-copy">{{ document.error_message }}</p>
          </div>
          <div class="document-stats">
            <span><strong>{{ document.mastered_count }}</strong> 已掌握</span>
            <span><strong>{{ document.block_counts?.passage || 0 }}</strong> 正文区块</span>
          </div>
          <div class="row-actions">
            <RouterLink
              v-if="document.status === 'done'"
              class="button ghost compact"
              :to="`/documents/${document.id}`"
            >
              查看 <ArrowRight :size="16" />
            </RouterLink>
            <button
              v-if="document.status === 'error'"
              class="icon-button"
              title="重新解析"
              @click="reprocess(document)"
            >
              <RotateCw :size="17" />
            </button>
            <button class="icon-button danger" title="删除" @click="removeDocument(document)">
              <Trash2 :size="17" />
            </button>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

