<template>
  <div class="app-container">
    <UploadForm
      v-if="!currentJobId"
      @job-started="onJobStarted"
    />
    <JobStatus
      v-else
      :jobId="currentJobId"
      @reset="onReset"
    />

    <!-- Footer -->
    <div class="footer" style="position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);">
      <img src="./assets/logo.svg" style="width: 100px; height: 60px;" alt="Logo" />
    </div>

    <!-- Contact us widget -->
    <ContactWidget />
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
    }
  },
  methods: {
    onJobStarted(jobId) {
      this.currentJobId = jobId
    },
    onReset() {
      this.currentJobId = null
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
</style>
