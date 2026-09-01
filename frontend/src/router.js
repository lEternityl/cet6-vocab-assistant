import { createRouter, createWebHashHistory } from "vue-router";

import CorpusPage from "./pages/CorpusPage.vue";
import DocumentPage from "./pages/DocumentPage.vue";
import HomePage from "./pages/HomePage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import StudyPage from "./pages/StudyPage.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "home", component: HomePage },
    { path: "/documents/:id", name: "document", component: DocumentPage },
    { path: "/documents/:id/study", name: "study", component: StudyPage },
    { path: "/corpus", name: "corpus", component: CorpusPage },
    { path: "/settings", name: "settings", component: SettingsPage },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

export default router;
