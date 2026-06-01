<template>
    <div class="job-status card fade-in-up">
        <!-- Header -->
        <div class="status-header">
            <div
                v-if="status === 'done' || status === 'error'"
                class="status-icon-wrapper"
                :class="statusClass"
            >
                <svg
                    v-if="status === 'done'"
                    width="28"
                    height="28"
                    viewBox="0 0 28 28"
                    fill="none"
                >
                    <path
                        d="M8 14L12 18L20 10"
                        stroke="currentColor"
                        stroke-width="2.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                </svg>
                <svg
                    v-else-if="status === 'error'"
                    width="28"
                    height="28"
                    viewBox="0 0 28 28"
                    fill="none"
                >
                    <path
                        d="M10 10L18 18M18 10L10 18"
                        stroke="currentColor"
                        stroke-width="2.5"
                        stroke-linecap="round"
                    />
                </svg>
            </div>
            <h2 class="status-title">{{ statusTitle }}</h2>
            <p class="status-subtitle">{{ statusSubtitle }}</p>
        </div>

        <!-- Pipeline steps -->
        <div class="pipeline">
            <div
                v-for="(step, idx) in steps"
                :key="step.id"
                class="pipeline-step"
                :class="stepClass(step.id)"
            >
                <div class="step-indicator">
                    <div class="step-dot">
                        <svg
                            v-if="isStepComplete(step.id)"
                            width="14"
                            height="14"
                            viewBox="0 0 14 14"
                            fill="none"
                        >
                            <path
                                d="M3 7L6 10L11 4"
                                stroke="currentColor"
                                stroke-width="2"
                                stroke-linecap="round"
                                stroke-linejoin="round"
                            />
                        </svg>
                        <span
                            v-else-if="isStepActive(step.id)"
                            class="step-spinner"
                        ></span>
                        <span v-else class="step-number">{{ idx + 1 }}</span>
                    </div>
                    <div
                        v-if="idx < steps.length - 1"
                        class="step-connector"
                        :class="{
                            'step-connector--done': isStepComplete(step.id),
                        }"
                    ></div>
                </div>
                <p class="step-label">{{ stepLabel(step) }}</p>
            </div>
        </div>

        <!-- Error message -->
        <div v-if="status === 'error'" class="error-box">
            <p>⚠️ {{ error || "An unexpected error occurred." }}</p>
        </div>

        <!-- Done actions -->
        <div v-if="status === 'done'" class="done-actions">
            <p class="done-msg">
                An email with the download link has been sent!
            </p>
            <div class="done-buttons">
                <button class="btn btn-ghost" @click="$emit('reset')">
                    Process Another
                </button>
                <a
                    :href="downloadZipUrl"
                    class="btn btn-primary"
                    style="text-decoration: none"
                    :download="`${jobId}.zip`"
                >
                    Download Results
                </a>
            </div>
        </div>

        <!-- Job ID -->
        <p class="job-id">
            Job ID: <code>{{ jobId }}</code>
        </p>
    </div>
</template>

<script>
const STAGES = [
    "queued",
    "stabilizing",
    "detecting",
    "tracking",
    "csv_postprocessing",
    "emailing",
    "done",
];

export default {
    name: "JobStatus",
    props: {
        jobId: { type: String, required: true },
    },
    emits: ["reset"],
    data() {
        return {
            status: "processing",
            stage: "queued",
            progress: 0,
            error: null,
            pollTimer: null,
            steps: [
                { id: "stabilizing", label: "Image Stabilization" },
                { id: "detecting", label: "Object Detection" },
                { id: "tracking", label: "Object Tracking" },
                { id: "csv_postprocessing", label: "CSV Postprocessing" },
                { id: "emailing", label: "Sending Email" },
            ],
        };
    },
    computed: {
        statusClass() {
            if (this.status === "done") return "status--done";
            if (this.status === "error") return "status--error";
            return "status--processing";
        },
        statusTitle() {
            if (this.status === "done") return "Processing Complete!";
            if (this.status === "error") return "Processing Failed";
            return "Processing Your Video";
        },
        statusSubtitle() {
            if (this.status === "done")
                return "Your video has been fully processed and results have been emailed.";
            if (this.status === "error")
                return "An error occurred and processing could not be completed.";
            const descriptions = {
                queued: "Your job is in the queue and will begin shortly...",
                stabilizing: "Smoothing out camera shake and motion artifacts...",
                detecting: "Identifying and locating objects in each frame...",
                tracking: "Following detected objects across frames over time...",
                csv_postprocessing:
                    "Compiling detection data into structured CSV results...",
                emailing: "Packaging results and sending them to your inbox...",
            };
            return descriptions[this.stage] ?? "Waiting in queue…";
        },
        downloadZipUrl() {
            return `/api/download/${this.jobId}/zip`;
        },
        currentStageIndex() {
            return STAGES.indexOf(this.stage);
        },
    },
    mounted() {
        this.startPolling();
    },
    beforeUnmount() {
        this.stopPolling();
    },
    methods: {
        stepLabel(step) {
            const showProgress =
                this.isStepActive(step.id) && this.progress > 0;
            return showProgress
                ? `${step.label} · ${this.progress}%`
                : step.label;
        },
        isStepComplete(stepId) {
            const stepIdx = STAGES.indexOf(stepId);
            return this.currentStageIndex > stepIdx || this.status === "done";
        },
        isStepActive(stepId) {
            return (
                this.stage === stepId &&
                this.status !== "done" &&
                this.status !== "error"
            );
        },
        stepClass(stepId) {
            if (this.isStepComplete(stepId)) return "pipeline-step--done";
            if (this.isStepActive(stepId)) return "pipeline-step--active";
            return "";
        },
        startPolling() {
            this.fetchStatus();
            this.pollTimer = setInterval(() => this.fetchStatus(), 2000);
        },
        stopPolling() {
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        },
        async fetchStatus() {
            try {
                const res = await fetch(`/api/status/${this.jobId}`);
                const data = await res.json();

                this.status = data.status;
                this.stage = data.stage;
                this.progress = data.progress;
                this.error = data.error;

                if (data.status === "done" || data.status === "error") {
                    this.stopPolling();
                }
            } catch {
                // keep trying
            }
        },
    },
};
</script>

<style scoped>
.job-status {
    width: 100%;
    max-width: 480px;
    padding: 36px 32px 32px;
}

/* Header */
.status-header {
    text-align: center;
    margin-bottom: 28px;
}

.status-icon-wrapper {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 14px;
}

.status--processing {
    background: rgba(126, 153, 163, 0.12);
    color: var(--accent);
}

.status--done {
    background: var(--success-light);
    color: var(--success);
}

.status--error {
    background: var(--error-light);
    color: var(--error);
}

.status-title {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
}

.status-subtitle {
    color: var(--text-muted);
    font-size: 13px;
}

/* Pipeline */
.pipeline {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: 24px;
}

.pipeline-step {
    display: flex;
    gap: 14px;
    align-items: flex-start;
}

.step-indicator {
    align-self: stretch;
    display: flex;
    flex-direction: column;
    align-items: center;
}

.step-dot {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: #f3f4f6;
    border: 1.5px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    transition: all 0.25s ease;
}

.pipeline-step--active .step-dot {
    border-color: var(--accent);
    background: rgba(126, 153, 163, 0.1);
    color: var(--accent);
}

.pipeline-step--done .step-dot {
    border-color: var(--success);
    background: var(--success-light);
    color: var(--success);
}

.step-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(126, 153, 163, 0.3);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
}

.step-number {
    font-size: 11px;
}

.step-connector {
    flex: 1;
    width: 1.5px;
    background: var(--border);
    transition: background 0.25s;
}

.step-connector--done {
    background: var(--success);
}

.step-label {
    box-sizing: content-box;
    height: 30px;
    padding-bottom: 18px;
    font-weight: 600;
    font-size: 13px;
    color: var(--text-primary);
    margin: 0;
    display: flex;
    align-items: center;
}

.pipeline-step:last-child .step-label {
    padding-bottom: 0;
}

.pipeline-step:not(.pipeline-step--done):not(.pipeline-step--active)
    .step-label {
    color: var(--text-muted);
}

/* Error */
.error-box {
    background: var(--error-light);
    border: 1px solid rgba(220, 38, 38, 0.2);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    color: var(--error);
    font-size: 13px;
    margin-bottom: 20px;
}

/* Done */
.done-actions {
    text-align: center;
    margin-bottom: 20px;
}

.done-msg {
    color: var(--success);
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 18px;
}

.done-buttons {
    display: flex;
    gap: 10px;
}

.done-buttons .btn {
    flex: 1;
}

.btn-ghost {
    background: #f3f4f6;
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 12px 20px;
    border-radius: var(--radius-md);
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-ghost:hover {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-light);
}

/* Job ID */
.job-id {
    text-align: center;
    color: var(--text-muted);
    font-size: 11px;
    margin-top: 8px;
}

.job-id code {
    font-family: var(--font-mono);
    color: var(--text-secondary);
    background: rgba(129, 129, 129, 0.2);
    padding: 2px 6px;
    border-radius: 4px;
}
</style>
