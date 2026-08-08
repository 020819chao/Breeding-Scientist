<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type ThemeName = "green" | "gold" | "purple";
type Language = "zh" | "en";

const themes: Record<ThemeName, { label: string; color: string; hover: string; pressed: string }> = {
  green: { label: "绿色", color: "#16865f", hover: "#2a9d76", pressed: "#0f6848" },
  gold: { label: "金色", color: "#b8771e", hover: "#ca8c35", pressed: "#8e5b12" },
  purple: { label: "紫色", color: "#7046b6", hover: "#855fc3", pressed: "#57358f" },
};

const language = ref<Language>((localStorage.getItem("co-scientist-language") as Language) || "zh");
const themeName = ref<ThemeName>((localStorage.getItem("co-scientist-theme") as ThemeName) || "green");
const budget = ref(2);
const nInitial = ref(3);
const maxHypotheses = ref<number | undefined>(undefined);
const wallClock = ref(7200);
const goal = ref("");
const preferences = ref("");

const currentTheme = computed(() => themes[themeName.value]);
const themeStyles = computed(() => ({
  "--theme-color": currentTheme.value.color,
  "--theme-color-hover": currentTheme.value.hover,
  "--theme-color-pressed": currentTheme.value.pressed,
  "--color-primary-6": currentTheme.value.color,
  "--color-primary-7": currentTheme.value.pressed,
  "--color-primary-light-1": `${currentTheme.value.color}18`,
}));
const isEnglish = computed(() => language.value === "en");
const copy = computed(() => isEnglish.value ? {
  brandSubtitle: "Breeding Scientist",
  knowledge: "Knowledge Base",
  monitor: "Monitor",
  pageKicker: "BREEDING SCIENTIST · NEW PLAN",
  title: "Define this breeding task",
  description: "Describe what you want to solve and which conditions matter. The scientist will use them to shape the research run.",
  goal: "Breeding goal",
  goalPlaceholder: "For example: improve foxtail millet drought tolerance without sacrificing yield...",
  preferences: "Preferences",
  preferencesOptional: "Optional",
  preferencesPlaceholder: "Add crop background, preferred evidence, field constraints, or validation requirements...",
  budget: "Budget (USD)",
  initial: "Initial hypotheses",
  maximum: "Maximum hypotheses",
  wallClock: "Time limit (s)",
  useDefault: "Use goal default",
  submit: "Create breeding plan",
  cancel: "Cancel",
  previewKicker: "PLAN PREVIEW",
  previewTitle: "A focused research run",
  previewDescription: "Your inputs will guide a compact, traceable workflow.",
  stepGoal: "Clarify the goal",
  stepEvidence: "Connect evidence",
  stepPlan: "Generate the route",
  language: "中文",
  theme: "Theme",
  plans: "Breeding Plans",
  loading: "Loading defaults...",
} : {
  brandSubtitle: "育种科学家",
  knowledge: "知识库",
  monitor: "监控中心",
  pageKicker: "BREEDING SCIENTIST · 新建方案",
  title: "定义本次育种任务",
  description: "说明你想解决什么，以及哪些条件必须满足，育种科学家会据此组织本次研究运行。",
  goal: "育种目标",
  goalPlaceholder: "例如：在不牺牲产量的前提下，提高谷子耐旱性……",
  preferences: "补充要求",
  preferencesOptional: "可选",
  preferencesPlaceholder: "补充作物背景、优先证据、田间限制或验证要求……",
  budget: "预算（USD）",
  initial: "初始假设数",
  maximum: "最大假设数",
  wallClock: "时间上限（秒）",
  useDefault: "使用目标默认值",
  submit: "创建育种方案",
  cancel: "取消",
  previewKicker: "方案预览",
  previewTitle: "一次聚焦的科研运行",
  previewDescription: "你的输入会驱动一条紧凑、可追溯的育种工作流。",
  stepGoal: "澄清育种目标",
  stepEvidence: "连接关键证据",
  stepPlan: "生成育种路线",
  language: "EN",
  theme: "色调",
  plans: "育种方案",
  loading: "正在读取默认配置……",
});

function toggleLanguage() {
  language.value = language.value === "zh" ? "en" : "zh";
  localStorage.setItem("co-scientist-language", language.value);
}

function selectTheme(value: string | number | Record<string, any> | undefined) {
  if (typeof value !== "string" || !(value in themes)) return;
  themeName.value = value as ThemeName;
  localStorage.setItem("co-scientist-theme", themeName.value);
}

onMounted(async () => {
  try {
    const response = await fetch("/api/session-form-config");
    if (!response.ok) return;
    const config = await response.json();
    if (typeof config.default_budget === "number") budget.value = config.default_budget;
    if (typeof config.wall_clock_seconds === "number") wallClock.value = config.wall_clock_seconds;
  } catch {
    // The backend defaults above keep the form usable when the config request is unavailable.
  }
});
</script>

<template>
  <div class="new-session-app" :style="themeStyles">
    <a-layout>
      <a-layout-header class="new-session-topbar">
        <div class="new-session-topbar-inner">
          <a class="new-session-brand" href="/">
            <span class="new-session-brand-mark">BS</span>
            <span><strong>Breeding Scientist</strong><small>{{ copy.brandSubtitle }}</small></span>
          </a>
          <nav class="new-session-nav" aria-label="主导航">
            <a href="/sessions">{{ copy.plans }}</a>
          </nav>
        </div>
      </a-layout-header>

      <a-layout-content>
        <main class="new-session-content">
          <div class="new-session-heading">
            <div>
              <div class="new-session-eyebrow"><span></span>{{ copy.pageKicker }}</div>
              <h1>{{ copy.title }}</h1>
              <p>{{ copy.description }}</p>
            </div>
          </div>

          <div class="new-session-grid">
            <a-card class="new-session-form-card" :bordered="false">
              <form method="POST" action="/sessions/new" class="new-session-form">
                <input type="hidden" name="goal" :value="goal" />
                <input type="hidden" name="preferences" :value="preferences" />
                <input type="hidden" name="budget_usd" :value="budget" />
                <input type="hidden" name="n_initial" :value="nInitial" />
                <input type="hidden" name="max_hypotheses" :value="maxHypotheses ?? ''" />
                <input type="hidden" name="wall_clock_seconds" :value="wallClock" />

                <div class="new-session-field">
                  <label>{{ copy.goal }} <em>*</em></label>
                  <a-textarea v-model="goal" :placeholder="copy.goalPlaceholder" :auto-size="{ minRows: 4, maxRows: 7 }" />
                </div>
                <div class="new-session-field">
                  <label>{{ copy.preferences }} <small>{{ copy.preferencesOptional }}</small></label>
                  <a-textarea v-model="preferences" :placeholder="copy.preferencesPlaceholder" :auto-size="{ minRows: 3, maxRows: 5 }" />
                </div>

                <div class="new-session-parameters">
                  <div class="new-session-field">
                    <label>{{ copy.budget }}</label>
                    <a-input-number v-model="budget" :min="0" :precision="2" :step="0.5" />
                  </div>
                  <div class="new-session-field">
                    <label>{{ copy.initial }}</label>
                    <a-input-number v-model="nInitial" :min="1" :precision="0" />
                  </div>
                  <div class="new-session-field">
                    <label>{{ copy.maximum }}</label>
                    <a-input-number v-model="maxHypotheses" :min="1" :precision="0" :placeholder="copy.useDefault" allow-clear />
                  </div>
                  <div class="new-session-field">
                    <label>{{ copy.wallClock }}</label>
                    <a-input-number v-model="wallClock" :min="60" :precision="0" />
                  </div>
                </div>

                <div class="new-session-form-actions">
                  <a-button type="text" class="new-session-cancel" href="/sessions">{{ copy.cancel }}</a-button>
                  <a-button type="primary" html-type="submit" size="large">{{ copy.submit }} <span>→</span></a-button>
                </div>
              </form>
            </a-card>

            <aside class="new-session-preview">
              <div class="new-session-preview-top"><span class="new-session-preview-icon">BS</span><span>{{ copy.previewKicker }}</span></div>
              <h2>{{ copy.previewTitle }}</h2>
              <p>{{ copy.previewDescription }}</p>
              <div class="new-session-preview-steps">
                <div><b>01</b><span>{{ copy.stepGoal }}</span></div>
                <div><b>02</b><span>{{ copy.stepEvidence }}</span></div>
                <div><b>03</b><span>{{ copy.stepPlan }}</span></div>
              </div>
              <div class="new-session-preview-note"><i></i>{{ isEnglish ? "Evidence-led · Traceable · Actionable" : "证据驱动 · 全程可追溯 · 面向行动" }}</div>
            </aside>
          </div>
        </main>
      </a-layout-content>
    </a-layout>
  </div>
</template>

<style scoped>
.new-session-app {
  min-height: 100vh;
  color: #17241f;
  background:
    radial-gradient(circle at 10% 0%, color-mix(in srgb, var(--theme-color) 10%, transparent), transparent 28%),
    #f7faf8;
}
.new-session-topbar { height: 64px; background: rgba(255, 255, 255, .88); border-bottom: 1px solid #e2ebe5; backdrop-filter: blur(18px); }
.new-session-topbar-inner { max-width: 1180px; height: 100%; margin: 0 auto; padding: 0 28px; display: flex; align-items: center; }
.new-session-brand { display: flex; align-items: center; gap: 10px; color: #17241f; text-decoration: none; }
.new-session-brand-mark { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 10px; color: #fff; background: var(--theme-color); font: 700 11px ui-monospace, monospace; box-shadow: 0 7px 16px color-mix(in srgb, var(--theme-color) 24%, transparent); }
.new-session-brand strong, .new-session-brand small { display: block; }
.new-session-brand strong { font-size: 15px; letter-spacing: -.02em; }
.new-session-brand small { margin-top: 2px; color: #83928a; font-size: 10px; }
.new-session-nav { display: flex; gap: 26px; margin-right: auto; }
.new-session-nav a { color: #66756d; font-size: 13px; text-decoration: none; transition: color .2s ease; }
.new-session-nav a:hover { color: var(--theme-color); }
.new-session-plain-button { color: #65736c; }
.new-session-theme-dot, .new-session-theme-option i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; }
.new-session-chevron { margin-left: 5px; color: #9ba7a1; }
.new-session-theme-option { display: flex; align-items: center; min-width: 94px; }
.new-session-theme-option b { margin-left: auto; color: var(--theme-color); }
.new-session-content { max-width: 1180px; margin: 0 auto; padding: 64px 28px 88px; }
.new-session-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 30px; }
.new-session-eyebrow { color: var(--theme-color); font: 700 10px ui-monospace, monospace; letter-spacing: .14em; }
.new-session-eyebrow span { display: inline-block; width: 18px; height: 1px; margin: 0 8px 3px 0; background: var(--theme-color); }
.new-session-heading h1 { max-width: 680px; margin: 14px 0 9px; font-size: clamp(34px, 4.2vw, 52px); line-height: 1.1; letter-spacing: -.065em; }
.new-session-heading p { max-width: 620px; margin: 0; color: #718078; font-size: 15px; line-height: 1.8; }
.new-session-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 22px; align-items: stretch; }
.new-session-form-card { border: 1px solid #e0eae3; border-radius: 22px; box-shadow: 0 18px 46px rgba(46, 84, 64, .07); }
.new-session-form-card :deep(.arco-card-body) { padding: 30px; }
.new-session-form { display: flex; flex-direction: column; gap: 23px; }
.new-session-field label { display: flex; align-items: baseline; gap: 8px; margin-bottom: 9px; color: #26362e; font-size: 14px; font-weight: 650; }
.new-session-field label em { color: #c87522; font-style: normal; }
.new-session-field label small { color: #9aa69f; font-size: 11px; font-weight: 400; }
.new-session-field :deep(.arco-textarea-wrapper), .new-session-field :deep(.arco-input-number) { border-radius: 12px; border-color: #dce7df; background: #fbfdfb; }
.new-session-field :deep(.arco-textarea-wrapper:hover), .new-session-field :deep(.arco-input-number:hover), .new-session-field :deep(.arco-textarea-wrapper.arco-textarea-focus), .new-session-field :deep(.arco-input-number-focused) { border-color: var(--theme-color); box-shadow: 0 0 0 3px color-mix(in srgb, var(--theme-color) 12%, transparent); }
.new-session-field :deep(.arco-textarea) { min-height: 92px; padding: 13px 14px; color: #27372f; font-size: 14px; line-height: 1.7; }
.new-session-field :deep(.arco-input-number) { width: 100%; height: 42px; }
.new-session-field :deep(.arco-input-number-input) { font-size: 14px; }
.new-session-parameters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; padding-top: 1px; }
.new-session-parameters .new-session-field { min-width: 0; }
.new-session-form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 14px; padding-top: 3px; }
.new-session-form-actions :deep(.arco-btn) { border-radius: 999px; }
.new-session-form-actions :deep(.new-session-cancel) { color: #7a8780; }
.new-session-form-actions :deep(.new-session-cancel:hover) { color: var(--theme-color); background: color-mix(in srgb, var(--theme-color) 7%, white); }
.new-session-form-actions :deep(.arco-btn-primary) { min-width: 170px; background: var(--theme-color); border-color: var(--theme-color); box-shadow: 0 10px 22px color-mix(in srgb, var(--theme-color) 22%, transparent); }
.new-session-form-actions :deep(.arco-btn-primary:hover) { background: var(--theme-color-hover); border-color: var(--theme-color-hover); transform: translateY(-1px); }
.new-session-preview { align-self: stretch; display: flex; flex-direction: column; min-height: 0; height: 100%; box-sizing: border-box; padding: 30px 28px; border: 1px solid color-mix(in srgb, var(--theme-color) 15%, #e0eae3); border-radius: 22px; color: #20352a; background: linear-gradient(150deg, color-mix(in srgb, var(--theme-color) 6%, white), #fff); box-shadow: 0 18px 42px color-mix(in srgb, var(--theme-color) 10%, transparent); }
.new-session-preview-top { display: flex; align-items: center; gap: 12px; color: var(--theme-color); font: 700 11px ui-monospace, monospace; letter-spacing: .13em; }
.new-session-preview-icon { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid color-mix(in srgb, var(--theme-color) 25%, #dce7df); border-radius: 10px; color: var(--theme-color); background: color-mix(in srgb, var(--theme-color) 7%, white); font-size: 11px; letter-spacing: 0; }
.new-session-preview h2 { margin: 37px 0 12px; color: #17241f; font-size: 29px; letter-spacing: -.05em; }
.new-session-preview p { max-width: 275px; margin: 0; color: #718078; font-size: 15px; line-height: 1.85; }
.new-session-preview-steps { display: grid; gap: 19px; margin-top: 39px; }
.new-session-preview-steps div { display: flex; align-items: center; gap: 14px; padding-bottom: 16px; border-bottom: 1px solid color-mix(in srgb, var(--theme-color) 13%, #edf2ee); }
.new-session-preview-steps b { color: var(--theme-color); font: 700 11px ui-monospace, monospace; }
.new-session-preview-steps span { font-size: 15px; }
.new-session-preview-note { display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 34px; color: #82918a; font-size: 12px; }
.new-session-preview-note i { width: 6px; height: 6px; border-radius: 50%; background: var(--theme-color); box-shadow: 0 0 0 4px color-mix(in srgb, var(--theme-color) 13%, transparent); }
@media (max-width: 900px) {
  .new-session-topbar-inner { gap: 18px; padding: 0 18px; }
  .new-session-nav { display: none; }
  .new-session-content { padding: 42px 18px 60px; }
  .new-session-heading { align-items: flex-start; flex-direction: column; }
  .new-session-grid { grid-template-columns: 1fr; }
  .new-session-preview { height: auto; min-height: auto; }
}
@media (max-width: 620px) {
  .new-session-topbar-inner { padding: 0 14px; }
  .new-session-topbar-inner > :last-child { gap: 0; }
  .new-session-topbar-inner > :last-child :deep(.new-session-plain-button) { display: none; }
  .new-session-form-card :deep(.arco-card-body) { padding: 21px 18px; }
  .new-session-parameters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .new-session-form-actions { justify-content: stretch; }
  .new-session-form-actions :deep(.arco-btn-primary) { flex: 1; }
}
</style>
