<script setup>
import { CheckCircle2, ChevronDown, LibraryBig, LoaderCircle, Search, TrendingUp } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const store = useAppStore();
const words = ref([]);
const loading = ref(true);
const level = ref("cet6");
const status = ref("all");
const search = ref("");
let timer;

const load = async () => {
  loading.value = true;
  try {
    const params = new URLSearchParams({ level: level.value, status: status.value, search: search.value, limit: "500" });
    words.value = await api.get(`/api/corpus/word-stats?${params}`);
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
};

watch([level, status], load);
watch(search, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(load, 250);
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
      <div class="callout-stat"><strong>{{ words.length }}</strong><small>当前可见词条</small></div>
    </section>

    <section class="workspace-card">
      <div class="toolbar">
        <label class="search-field"><Search :size="17" /><input v-model="search" placeholder="搜索历年词汇" /></label>
        <label class="select-field"><span>词库</span><select v-model="level"><option value="cet6">六级新增</option><option value="cet4">四级基础</option><option value="all">全部</option></select><ChevronDown :size="15" /></label>
        <label class="select-field"><span>状态</span><select v-model="status"><option value="all">全部</option><option value="new">未学习</option><option value="learning">学习中</option><option value="mastered">已掌握</option></select><ChevronDown :size="15" /></label>
      </div>
      <div v-if="loading" class="loading-panel"><LoaderCircle class="spin" /> 正在汇总历年词频</div>
      <div v-else-if="!words.length" class="empty-state compact-empty"><LibraryBig :size="32" /><h3>还没有跨试卷数据</h3><p>先上传并解析真题，这里会自动形成历年词频。</p></div>
      <div v-else class="table-wrap">
        <table class="word-table corpus-table">
          <thead><tr><th>#</th><th>词汇</th><th>释义</th><th class="numeric">学习范围</th><th class="numeric">全文</th><th class="numeric">出现试卷</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="(word, index) in words" :key="word.lemma">
              <td class="rank">{{ index + 1 }}</td>
              <td><strong class="word-name">{{ word.lemma }}</strong><small>{{ word.pos_label }} · /{{ word.phonetic?.split('|')[0] || '—' }}/</small></td>
              <td class="definition-cell">{{ word.definition }}</td>
              <td class="numeric frequency-cell">{{ word.study_frequency }}</td>
              <td class="numeric">{{ word.total_frequency }}</td>
              <td class="numeric"><span class="document-frequency">{{ word.document_frequency }} 套</span></td>
              <td><span class="mastery-pill" :class="word.status"><CheckCircle2 v-if="word.status === 'mastered'" :size="13" />{{ { new: '未学习', learning: '学习中', mastered: '已掌握', suspended: '已忽略' }[word.status] }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
