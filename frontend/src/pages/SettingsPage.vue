<script setup>
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  KeyRound,
  LoaderCircle,
  Pencil,
  Save,
  Server,
  ShieldCheck,
  X,
} from "lucide-vue-next";
import { onMounted, reactive, ref } from "vue";

import { api } from "../api";
import { useAppStore } from "../stores/app";

const store = useAppStore();
const config = ref(null);
const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const showForm = ref(false);
const blankForm = () => ({
  name: "我的模型",
  base_url: "https://llm-fnv9qmq682nwjkjo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  model_name: "qwen3.7-flash",
  temperature: 0.1,
  max_tokens: 2048,
  enable_thinking: false,
  api_key: "",
});
const form = reactive(blankForm());

const load = async () => {
  loading.value = true;
  try {
    const configs = await api.get("/api/model-configs");
    config.value = configs[0] || null;
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    loading.value = false;
  }
};

const openForm = () => {
  Object.assign(
    form,
    config.value
      ? {
          name: config.value.name,
          base_url: config.value.base_url,
          model_name: config.value.model_name,
          temperature: config.value.temperature,
          max_tokens: config.value.max_tokens,
          enable_thinking: config.value.enable_thinking,
          api_key: "",
        }
      : blankForm(),
  );
  showForm.value = true;
};

const save = async () => {
  saving.value = true;
  try {
    const payload = { ...form, task_type: "both", is_default: true };
    if (config.value) await api.put(`/api/model-configs/${config.value.id}`, payload);
    else await api.post("/api/model-configs", payload);
    showForm.value = false;
    store.notify("模型配置已保存");
    await load();
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    saving.value = false;
  }
};

const test = async () => {
  testing.value = true;
  try {
    const result = await api.post(`/api/model-configs/${config.value.id}/test`, {});
    store.notify(result.message, result.success ? "success" : "error");
    await load();
  } catch (error) {
    store.notify(error.message, "error");
  } finally {
    testing.value = false;
  }
};

onMounted(load);
</script>

<template>
  <div class="page settings-page">
    <header class="page-header settings-header">
      <div><p class="eyebrow">LOCAL AI SETTINGS</p><h1>模型是工具，语境才是主角。</h1><p class="lead">只需配置一个模型，例句翻译、单词记忆、句子分析共用；API Key 随配置保存在本地数据库。</p></div>
    </header>

    <section class="security-note">
      <span><ShieldCheck :size="23" /></span>
      <div><strong>密钥由你填写、你掌控</strong><p>API Key 仅保存在本机数据库，前端永不回显已保存的密钥。也可用 CET6_API_KEY 环境变量作为全局备用。</p></div>
    </section>

    <div v-if="loading" class="loading-panel"><LoaderCircle class="spin" /> 正在读取配置</div>
    <section v-else class="model-grid">
      <article v-if="config" class="model-card">
        <header>
          <span class="model-icon"><Bot :size="21" /></span>
          <div><div class="model-title-line"><h2>{{ config.name }}</h2></div><p>翻译 · 记忆 · 问答</p></div>
          <div class="model-actions"><button class="icon-button" @click="openForm"><Pencil :size="16" /></button></div>
        </header>
        <div class="model-name">{{ config.model_name }}</div>
        <dl>
          <div><dt><Server :size="14" /> API 地址</dt><dd>{{ config.base_url }}</dd></div>
          <div><dt><KeyRound :size="14" /> API Key</dt><dd>{{ config.has_api_key ? "已保存" : "未设置" }}</dd></div>
          <div><dt>参数</dt><dd>temperature {{ config.temperature }} · {{ config.max_tokens }} tokens · {{ config.enable_thinking ? "思考开启" : "思考关闭" }}</dd></div>
        </dl>
        <footer>
          <span class="test-status" :class="config.last_test_status"><CheckCircle2 v-if="config.last_test_status === 'ok'" :size="15" /><CircleAlert v-else :size="15" />{{ config.last_test_status === "ok" ? "连接正常" : config.last_test_status === "error" ? "上次测试失败" : "尚未测试" }}</span>
          <button class="button small ghost" :disabled="testing" @click="test"><LoaderCircle v-if="testing" class="spin" :size="15" />测试连接</button>
        </footer>
      </article>
      <article v-else class="model-card empty">
        <p>尚未配置模型，AI 功能不可用。</p>
        <button class="button primary" @click="openForm"><Pencil :size="16" /> 配置模型</button>
      </article>
    </section>

    <Transition name="drawer">
      <div v-if="showForm" class="drawer-backdrop" @click.self="showForm = false">
        <aside class="settings-drawer">
          <button class="drawer-close" @click="showForm = false"><X :size="20" /></button>
          <p class="eyebrow">MODEL PROFILE</p>
          <h2>{{ config ? "编辑模型" : "配置模型" }}</h2>
          <form class="settings-form" @submit.prevent="save">
            <label><span>配置名称</span><input v-model="form.name" required /></label>
            <label><span>API Base URL</span><input v-model="form.base_url" required type="url" /></label>
            <label><span>模型名称</span><input v-model="form.model_name" required placeholder="qwen3.7-flash" /></label>
            <div class="form-row">
              <label><span>Temperature</span><input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" /></label>
              <label><span>最大 Tokens</span><input v-model.number="form.max_tokens" type="number" min="64" max="65536" /></label>
            </div>
            <label><span>API Key</span><input v-model="form.api_key" type="password" :placeholder="config ? '留空则不修改' : 'sk-…'" /></label>
            <label class="check-field"><input v-model="form.enable_thinking" type="checkbox" /><span><strong>开启思考模式</strong><small>通常建议关闭，以减少等待和费用。</small></span></label>
            <button class="button primary full" :disabled="saving"><LoaderCircle v-if="saving" class="spin" :size="17" /><Save v-else :size="17" />保存配置</button>
          </form>
        </aside>
      </div>
    </Transition>
  </div>
</template>
