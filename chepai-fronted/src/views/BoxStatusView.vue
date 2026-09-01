<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchEdgeBoxLogs, fetchEdgeBoxes, type EdgeBox, type EdgeLog } from '@/api/client'

const loading = ref(false)
const boxes = ref<EdgeBox[]>([])
const logOpen = ref(false)
const logTitle = ref('')
const logLoading = ref(false)
const logs = ref<EdgeLog[]>([])
const logIndex = ref(0)

let timer: number | null = null

function fmt(ts: string | null | undefined) {
  if (!ts) return '—'
  return ts.replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  try {
    boxes.value = await fetchEdgeBoxes()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function openLogs(row: EdgeBox) {
  logTitle.value = `${row.name}（${row.id}）`
  logOpen.value = true
  logIndex.value = 0
  logLoading.value = true
  try {
    logs.value = await fetchEdgeBoxLogs(row.id, 10)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载日志失败')
    logs.value = []
  } finally {
    logLoading.value = false
  }
}

function cameraHint(row: EdgeBox) {
  const cams = row.status?.cameras
  if (!cams || cams.length === 0) {
    return row.cameraCount != null ? `${row.cameraCount} 路` : '—'
  }
  const live = cams.filter((c) => c.alive).length
  return `${live}/${cams.length} 路在跑`
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => {
    void load()
  }, 15_000)
})

onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <p class="hint">工控机启动后会自动出现在此列表。超过约 90 秒无心跳视为离线。列表每 15 秒刷新。</p>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="boxes" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="160" />
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'info'" size="small">
            {{ row.online ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近心跳" width="180">
        <template #default="{ row }">{{ fmt(row.lastSeenAt) }}</template>
      </el-table-column>
      <el-table-column prop="hostname" label="主机名" width="160">
        <template #default="{ row }">{{ row.hostname || '—' }}</template>
      </el-table-column>
      <el-table-column label="相机" width="110">
        <template #default="{ row }">{{ cameraHint(row) }}</template>
      </el-table-column>
      <el-table-column prop="agentVersion" label="版本" width="100">
        <template #default="{ row }">{{ row.agentVersion || '—' }}</template>
      </el-table-column>
      <el-table-column label="磁盘" width="140">
        <template #default="{ row }">
          <span v-if="row.status?.disk">
            {{ row.status?.disk?.freeGb }} / {{ row.status?.disk?.totalGb }} GB
          </span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openLogs(row)">系统日志</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="logOpen" :title="`系统日志 · ${logTitle}`" width="860px" destroy-on-close>
      <div v-loading="logLoading">
        <p v-if="!logs.length" class="hint">还没有收到工控机上报的日志。</p>
        <template v-else>
          <el-select v-model="logIndex" style="width: 360px; margin-bottom: 12px">
            <el-option
              v-for="(item, i) in logs"
              :key="item.id"
              :label="`${fmt(item.collectedAt)} · ${item.source}`"
              :value="i"
            />
          </el-select>
          <pre class="log">{{ logs[logIndex]?.body }}</pre>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.hint {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.log {
  margin: 0;
  max-height: 60vh;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
