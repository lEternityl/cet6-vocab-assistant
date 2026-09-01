<script setup>
import {
  BookOpen,
  Files,
  GraduationCap,
  LibraryBig,
  Settings,
} from "lucide-vue-next";

import { useAppStore } from "./stores/app";

const store = useAppStore();
const navigation = [
  { to: "/", label: "我的题库", icon: Files },
  { to: "/corpus", label: "历年词频", icon: LibraryBig },
  { to: "/settings", label: "模型设置", icon: Settings },
];
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark"><BookOpen :size="22" /></span>
        <span>
          <strong>拾词</strong>
          <small>CET-6 CONTEXT LAB</small>
        </span>
      </RouterLink>

      <nav class="main-nav" aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to">
          <component :is="item.icon" :size="19" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-note">
        <GraduationCap :size="22" />
        <p><strong>从真题里学</strong><br />记住的不只是词义，还有它出现的理由。</p>
      </div>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>

    <nav class="mobile-nav" aria-label="移动端导航">
      <RouterLink v-for="item in navigation" :key="item.to" :to="item.to">
        <component :is="item.icon" :size="20" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>

    <Transition name="toast">
      <div v-if="store.toast" class="toast" :class="store.toast.type">
        {{ store.toast.message }}
      </div>
    </Transition>
  </div>
</template>

