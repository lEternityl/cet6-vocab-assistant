import { defineStore } from "pinia";

export const useAppStore = defineStore("app", {
  state: () => ({
    toast: null,
  }),
  actions: {
    notify(message, type = "success") {
      this.toast = { message, type, id: Date.now() };
      window.setTimeout(() => {
        if (this.toast?.message === message) this.toast = null;
      }, 3200);
    },
  },
});

