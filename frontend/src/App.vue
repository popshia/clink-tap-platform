<template>
  <div class="app-container">
    <UploadForm
      v-if="!currentJobId"
      :devMode="devMode"
      @job-started="onJobStarted"
    />
    <JobStatus
      v-else
      :jobId="currentJobId"
      @reset="onReset"
    />

    <!-- Footer (triple-click the logo to toggle developer mode) -->
    <div class="footer" style="position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);">
      <img
        src="./assets/logo.svg"
        :class="{ 'logo--dev': devMode }"
        style="width: 100px; height: 60px; cursor: pointer;"
        alt="Logo"
        @click="onLogoClick"
      />
    </div>

    <!-- Contact us widget -->
    <ContactWidget />

    <!-- Build commit pill — hover reveals the latest commit message -->
    <div class="commit-pill">
      v{{ commitDate }}
      <span class="commit-pill__log">{{ commitLog }}</span>
    </div>
  </div>
</template>

<script>
import UploadForm from './components/UploadForm.vue'
import JobStatus from './components/JobStatus.vue'
import ContactWidget from './components/ContactWidget.vue'

export default {
  name: 'App',
  components: { UploadForm, JobStatus, ContactWidget },
  data() {
    return {
      currentJobId: null,
      devMode: false,
      logoClicks: [],
      commitDate: __COMMIT_DATE__,
      commitLog: __COMMIT_LOG__,
    }
  },
  methods: {
    onJobStarted(jobId) {
      this.currentJobId = jobId
    },
    onReset() {
      this.currentJobId = null
    },
    onLogoClick() {
      // Triple-click within 600ms toggles developer mode.
      const now = Date.now()
      this.logoClicks = this.logoClicks.filter((t) => now - t < 600)
      this.logoClicks.push(now)
      if (this.logoClicks.length >= 3) {
        this.devMode = !this.devMode
        this.logoClicks = []
      }
    },
  },
}
</script>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 32px 16px;
  position: relative;
}

.footer {
  margin-top: 28px;
  opacity: 0.7;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Developer mode active — subtle tint + glow on the logo */
.logo--dev {
  filter: drop-shadow(0 0 6px var(--accent));
}

/* Build commit pill — fixed bottom-left, hover reveals the changelog */
.commit-pill {
  position: fixed;
  bottom: 20px;
  left: 16px;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--accent-light);
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: default;
}

.commit-pill__log {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: max-content;
  max-width: 320px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--accent-light);
  color: var(--accent);
  font-size: 12px;
  font-weight: bold;
  line-height: 1.5;
  white-space: pre-wrap;
  text-align: left;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.15s;
  pointer-events: none;
}

.commit-pill:hover .commit-pill__log {
  opacity: 1;
  visibility: visible;
}
</style>
