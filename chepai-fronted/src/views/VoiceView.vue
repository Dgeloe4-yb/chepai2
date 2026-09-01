<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VOICE_ALERT_TYPES,
  fetchEdgeBoxes,
  fetchVoiceBlob,
  fetchVoiceClips,
  uploadVoice,
  type EdgeBox,
  type VoiceClip,
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const visibleTypes = computed(() => VOICE_ALERT_TYPES.filter((t) => auth.hasFeature(t.value)))

const boxes = ref<EdgeBox[]>([])
const boxId = ref('')
const clips = ref<VoiceClip[]>([])
const loading = ref(false)
const uploading = ref<string | null>(null)
const previewUrl = ref<string | null>(null)

const clipByType = computed(() => {
  const map = new Map<string, VoiceClip>()
  for (const c of clips.value) map.set(c.alertType, c)
  return map
})

async function loadBoxes() {
  boxes.value = await fetchEdgeBoxes()
  if (!boxId.value && boxes.value.length > 0) {
    boxId.value = boxes.value[0]!.id
  }
}

async function loadClips() {
  if (!boxId.value) {
    clips.value = []
    return
  }
  loading.value = true
  try {
    clips.value = await fetchVoiceClips(boxId.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载语音失败')
  } finally {
    loading.value = false
  }
}

async function onFile(alertType: string, ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !boxId.value) return
  uploading.value = alertType
  try {
    await uploadVoice(boxId.value, alertType, file)
    ElMessage.success('已上传，工控机会自动拉取')
    await loadClips()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '上传失败')
  } finally {
    uploading.value = null
  }
}

async function preview(alertType: string) {
  if (!boxId.value) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  const blob = await fetchVoiceBlob(boxId.value, alertType)
  previewUrl.value = URL.createObjectURL(blob)
}

onMounted(async () => {
  await loadBoxes()
  await loadClips()
})

watch(boxId, () => {
  void loadClips()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="boxId" placeholder="工控机" style="width: 280px">
        <el-option v-for="b in boxes" :key="b.id" :label="`${b.name} (${b.id})`" :value="b.id" />
      </el-select>
      <el-button @click="loadClips" :loading="loading">刷新</el-button>
    </div>
    <p class="hint">未上传时用工控机本地默认语音。上传 WAV（RIFF）后，该告警类型改用自定义文件。</p>

    <el-table :data="visibleTypes" v-loading="loading" row-key="value" stripe>
      <el-table-column prop="label" label="告警" width="160" />
      <el-table-column prop="value" label="类型" width="180" />
      <el-table-column label="当前文件">
        <template #default="{ row }">
          <span v-if="clipByType.get(row.value)">
            {{ clipByType.get(row.value)?.originalName || '已上传' }}
            · {{ clipByType.get(row.value)?.updatedAt }}
          </span>
          <span v-else class="muted">未上传（用工控机本地默认）</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <label class="upload">
            <input type="file" accept="audio/wav,.wav" @change="onFile(row.value, $event)" />
            {{ uploading === row.value ? '上传中…' : '上传 WAV' }}
          </label>
          <el-button
            v-if="clipByType.get(row.value)"
            link
            type="primary"
            @click="preview(row.value)"
          >
            试听
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <audio v-if="previewUrl" :src="previewUrl" controls autoplay class="player" />
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
}
.hint,
.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.upload {
  margin-right: 8px;
  cursor: pointer;
  color: var(--el-color-primary);
  font-size: 13px;
}
.upload input {
  display: none;
}
.player {
  margin-top: 16px;
  width: 100%;
  max-width: 480px;
}
</style>
