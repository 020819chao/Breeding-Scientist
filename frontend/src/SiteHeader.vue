<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { IconTranslate } from "@arco-design/web-vue/es/icon";

type ThemeName = "green" | "gold" | "purple";

const props = defineProps<{
  active?: "knowledge" | "sessions" | "none";
  language?: "zh" | "en";
}>();

const emit = defineEmits<{
  (event: "toggle-language"): void;
}>();

const themes: Record<ThemeName, { label: string; color: string; hover: string; pressed: string; soft: string }> = {
  green: { label: "绿色", color: "#16865f", hover: "#2a9d76", pressed: "#0f6848", soft: "#eaf7ef" },
  gold: { label: "金色", color: "#b8771e", hover: "#ca8c35", pressed: "#8e5b12", soft: "#fff6e7" },
  purple: { label: "紫色", color: "#7046b6", hover: "#855fc3", pressed: "#57358f", soft: "#f3edff" },
};

const themeName = ref<ThemeName>((localStorage.getItem("co-scientist-theme") as ThemeName) || "green");
const isEnglish = computed(() => props.language === "en");
const themeLabels: Record<"zh" | "en", Record<ThemeName, string>> = {
  zh: { green: "绿色", gold: "金色", purple: "紫色" },
  en: { green: "Green", gold: "Gold", purple: "Purple" },
};

function applyTheme(name: ThemeName) {
  const theme = themes[name];
  const root = document.documentElement;
  root.style.setProperty("--theme-color", theme.color);
  root.style.setProperty("--theme-color-hover", theme.hover);
  root.style.setProperty("--theme-color-pressed", theme.pressed);
  root.style.setProperty("--theme-soft", theme.soft);
  root.style.setProperty("--color-primary-5", theme.hover);
  root.style.setProperty("--color-primary-6", theme.color);
  root.style.setProperty("--color-primary-7", theme.pressed);
  localStorage.setItem("co-scientist-theme", name);
}

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  applyTheme(themeName.value);
}

onMounted(() => applyTheme(themeName.value));
</script>

<template>
  <header class="site-header">
    <div class="site-header-inner">
      <a href="/" class="site-header-brand" :aria-label="isEnglish ? 'Breeding Scientist' : '育种科学家'">
        <span class="site-header-mark">BS</span>
        <span><strong>Breeding Scientist</strong><small>{{ isEnglish ? "Breeding Scientist" : "育种科学家" }}</small></span>
      </a>

      <nav class="site-header-nav" :aria-label="isEnglish ? 'Main navigation' : '主导航'">
        <a href="/knowledge" :class="{ active: props.active === 'knowledge' }">{{ isEnglish ? "Knowledge Base" : "知识库" }}</a>
        <a href="/sessions" :class="{ active: props.active === 'sessions' }">{{ isEnglish ? "Breeding Plans" : "育种方案" }}</a>
      </nav>

      <div class="site-header-actions">
        <button type="button" class="site-header-pill" :aria-label="isEnglish ? 'Switch language' : '切换语言'" @click="emit('toggle-language')">
          <IconTranslate /> <span>{{ isEnglish ? "中文" : "English" }}</span>
        </button>
        <a-dropdown trigger="click" @select="selectTheme">
          <button type="button" class="site-header-pill site-header-theme">
            <i :style="{ background: themes[themeName].color }"></i><span>{{ isEnglish ? "Theme" : "色调" }}</span><b>⌄</b>
          </button>
          <template #content>
            <a-doption v-for="(theme, key) in themes" :key="key" :value="key">
              <span class="site-header-theme-option"><i :style="{ background: theme.color }"></i>{{ themeLabels[isEnglish ? "en" : "zh"][key as ThemeName] }}<b v-if="themeName === key">✓</b></span>
            </a-doption>
          </template>
        </a-dropdown>
        <a href="/sessions/new" class="site-header-new-session">{{ isEnglish ? "New breeding session" : "新建育种会话" }}</a>
      </div>
    </div>
  </header>
</template>

<style>
.site-header { position: relative; z-index: 20; height: 88px; border-bottom: 1px solid #e2ebe5; background: rgba(255,255,255,.93); box-shadow: 0 10px 30px rgba(71,102,83,.045); backdrop-filter: blur(18px); }
.site-header-inner { max-width: 1440px; height: 100%; margin: 0 auto; padding: 0 28px; display: flex; align-items: center; gap: 42px; }
.site-header-brand { display: inline-flex; align-items: center; gap: 12px; color: #17241f; text-decoration: none; flex: 0 0 auto; }
.site-header-mark { display: grid; width: 48px; height: 48px; place-items: center; border-radius: 15px; color: #fff; background: var(--theme-color, #16865f); box-shadow: 0 10px 22px color-mix(in srgb, var(--theme-color, #16865f) 23%, transparent); font: 700 14px Georgia, serif; }
.site-header-brand strong, .site-header-brand small { display: block; }
.site-header-brand strong { font-size: 20px; line-height: 1.05; letter-spacing: -.035em; }
.site-header-brand small { margin-top: 4px; color: #87968e; font-size: 11px; }
.site-header-nav { display: flex; align-items: stretch; align-self: stretch; gap: 30px; margin-right: auto; }
.site-header-nav a { position: relative; display: inline-flex; align-items: center; color: #68776e; font-size: 15px; text-decoration: none; transition: color .18s ease; }
.site-header-nav a:hover, .site-header-nav a.active { color: #17241f; }
.site-header-nav a.active::after { content: ""; position: absolute; right: 0; bottom: 0; left: 0; height: 3px; border-radius: 99px 99px 0 0; background: var(--theme-color, #16865f); }
.site-header-actions { display: flex; align-items: center; gap: 12px; flex: 0 0 auto; }
.site-header-pill { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 17px; border: 1px solid color-mix(in srgb, var(--theme-color, #16865f) 14%, #e2ebe5); border-radius: 999px; color: var(--theme-color, #16865f); background: color-mix(in srgb, var(--theme-color, #16865f) 3%, #fff); font: inherit; font-size: 14px; cursor: pointer; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.site-header-pill:hover { border-color: color-mix(in srgb, var(--theme-color, #16865f) 34%, #dfe9e2); box-shadow: 0 7px 18px color-mix(in srgb, var(--theme-color, #16865f) 11%, transparent); transform: translateY(-1px); }
.site-header-theme i, .site-header-theme-option i { display: inline-block; width: 9px; height: 9px; margin-right: 2px; border-radius: 50%; }
.site-header-theme b { margin-left: 3px; color: #99a49d; font-size: 13px; font-weight: 500; }
.site-header-theme-option { display: flex; min-width: 100px; align-items: center; }
.site-header-theme-option b { margin-left: auto; color: var(--theme-color, #16865f); }
.site-header-new-session { display: inline-flex; min-height: 44px; align-items: center; padding: 0 20px; border-radius: 999px; color: #fff; background: var(--theme-color, #16865f); box-shadow: 0 10px 24px color-mix(in srgb, var(--theme-color, #16865f) 23%, transparent); font-size: 14px; font-weight: 700; text-decoration: none; transition: background .18s ease, box-shadow .18s ease, transform .18s ease; }
.site-header-new-session:hover { color: #fff; background: var(--theme-color-hover, #2a9d76); box-shadow: 0 13px 28px color-mix(in srgb, var(--theme-color, #16865f) 28%, transparent); transform: translateY(-1px); }
@media (max-width: 900px) { .site-header-inner { gap: 20px; padding: 0 20px; }.site-header-nav { gap: 20px; }.site-header-actions { gap: 7px; }.site-header-pill { padding: 0 12px; }.site-header-brand strong { font-size: 17px; } }
@media (max-width: 680px) { .site-header { height: 72px; }.site-header-inner { padding: 0 14px; gap: 12px; }.site-header-mark { width: 40px; height: 40px; border-radius: 13px; }.site-header-brand small { display: none; }.site-header-nav { display: none; }.site-header-actions { margin-left: auto; }.site-header-pill { min-height: 38px; padding: 0 10px; font-size: 12px; }.site-header-theme span { display: none; }.site-header-new-session { min-height: 38px; padding: 0 12px; font-size: 12px; } }
</style>
