<script setup>
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from "lucide-vue-next";
import { onMounted, reactive, ref } from "vue";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const store = useAppStore();
const configs = ref([]);
const loading = ref(true);
const saving = ref(false);
const testingId = ref(null);
const editingId = ref(null);
const showForm = ref(false);
const blankForm = () => ({
  name: "",
  base_url: "https://llm-fnv9qmq682nwjkjo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  model_name: "qwen3.7-flash",
  task_type: "translation",
  temperature: 0.1,
  max_tokens: 2048,
  enable_thinking: false,
  is_default: false,
  api_key: "",
});
const form = reactive(blankForm());

const load = async () => {
  loading.value = true;
  try {
    configs.value = await api.get("/api/model-configs");
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
};

const openCreate = () => {
  editingId.value = null;
  Object.assign(form, blankForm());
  showForm.value = true;
};

const openEdit = (config) => {
  editingId.value = config.id;
  Object.assign(form, { ...config, api_key: "" });
  showForm.value = true;
};

const save = async () => {
  saving.value = true;
  try {
    if (editingId.value) await api.put(`/api/model-configs/${editingId.value}`, form);
    else await api.post("/api/model-configs", form);
    showForm.value = false;
    store.notify("模型配置已保存");
    await load();
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    saving.value = false;
  }
};

const test = async (config) => {
  testingId.value = config.id;
  try {
    const result = await api.post(`/api/model-configs/${config.id}/test`, {});
    store.notify(result.message, result.success ? "success" : "error");
    await load();
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    testingId.value = null;
  }
};

const remove = async (config) => {
  if (!window.confirm(`确认删除模型配置“${config.name}”？`)) return;
  try {
    await api.delete(`/api/model-configs/${config.id}`);
    store.notify("模型配置已删除");
    await load();
  } catch (error) {
    store.notify(error.message, "error");
  }
};

onMounted(load);
</script>

<template>
  <div class="page settings-page">
    <header class="page-header settings-header">
      <div><p class="eyebrow">LOCAL AI SETTINGS</p><h1>模型是工具，语境才是主角。</h1><p class="lead">翻译和阅读问答可使用不同模型；密钥写入系统钥匙串，不进入数据库。</p></div>
      <button class="button primary" @click="openCreate"><Plus :size="17" /> 添加模型</button>
    </header>

    <section class="security-note">
      <span><ShieldCheck :size="23" /></span>
      <div><strong>本地优先的密钥策略</strong><p>前端永不读取已保存密钥；服务器日志也不会输出 Authorization 内容。若系统钥匙串不可用，可设置 CET6_API_KEY 环境变量。</p></div>
    </section>

    <div v-if="loading" class="loading-panel"><LoaderCircle class="spin" /> 正在读取配置</div>
    <section v-else class="model-grid">
      <article v-for="config in configs" :key="config.id" class="model-card">
        <header>
          <span class="model-icon"><Bot v-if="config.task_type === 'chat'" :size="21" /><Zap v-else :size="21" /></span>
          <div><div class="model-title-line"><h2>{{ config.name }}</h2><span v-if="config.is_default" class="default-chip">默认</span></div><p>{{ config.task_type === 'translation' ? '例句翻译' : config.task_type === 'chat' ? '阅读问答' : '翻译与问答' }}</p></div>
          <div class="model-actions"><button class="icon-button" @click="openEdit(config)"><Pencil :size="16" /></button><button class="icon-button danger" @click="remove(config)"><Trash2 :size="16" /></button></div>
        </header>
        <div class="model-name">{{ config.model_name }}</div>
        <dl>
          <div><dt><Server :size="14" /> API 地址</dt><dd>{{ config.base_url }}</dd></div>
          <div><dt><KeyRound :size="14" /> API Key</dt><dd>{{ config.has_api_key ? "已存入钥匙串" : "未设置" }}</dd></div>
          <div><dt>参数</dt><dd>temperature {{ config.temperature }} · {{ config.max_tokens }} tokens · {{ config.enable_thinking ? "思考开启" : "思考关闭" }}</dd></div>
        </dl>
        <footer>
          <span class="test-status" :class="config.last_test_status"><CheckCircle2 v-if="config.last_test_status === 'ok'" :size="15" /><CircleAlert v-else :size="15" />{{ config.last_test_status === "ok" ? "连接正常" : config.last_test_status === "error" ? "上次测试失败" : "尚未测试" }}</span>
          <button class="button small ghost" :disabled="testingId === config.id" @click="test(config)"><LoaderCircle v-if="testingId === config.id" class="spin" :size="15" />测试连接</button>
        </footer>
      </article>
    </section>

    <Transition name="drawer">
      <div v-if="showForm" class="drawer-backdrop" @click.self="showForm = false">
        <aside class="settings-drawer">
          <button class="drawer-close" @click="showForm = false"><X :size="20" /></button>
          <p class="eyebrow">MODEL PROFILE</p>
          <h2>{{ editingId ? "编辑模型配置" : "添加模型配置" }}</h2>
          <form class="settings-form" @submit.prevent="save">
            <label><span>配置名称</span><input v-model="form.name" required placeholder="例如：千问快速翻译" /></label>
            <label><span>API Base URL</span><input v-model="form.base_url" required type="url" /></label>
            <label><span>模型名称</span><input v-model="form.model_name" required placeholder="qwen3.7-flash" /></label>
            <div class="form-row">
              <label><span>任务类型</span><select v-model="form.task_type"><option value="translation">例句翻译</option><option value="chat">阅读问答</option><option value="both">两者都用</option></select></label>
              <label><span>最大 Tokens</span><input v-model.number="form.max_tokens" type="number" min="64" max="65536" /></label>
            </div>
            <div class="form-row">
              <label><span>Temperature</span><input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" /></label>
              <label><span>API Key</span><input v-model="form.api_key" type="password" :placeholder="editingId ? '留空则不修改' : 'sk-…'" /></label>
            </div>
            <label class="check-field"><input v-model="form.enable_thinking" type="checkbox" /><span><strong>开启思考模式</strong><small>翻译通常建议关闭，以减少等待和费用。</small></span></label>
            <label class="check-field"><input v-model="form.is_default" type="checkbox" /><span><strong>设为该任务默认模型</strong><small>同一任务仅保留一个默认配置。</small></span></label>
            <button class="button primary full" :disabled="saving"><LoaderCircle v-if="saving" class="spin" :size="17" /><Save v-else :size="17" />保存配置</button>
          </form>
        </aside>
      </div>
    </Transition>
  </div>
</template>

