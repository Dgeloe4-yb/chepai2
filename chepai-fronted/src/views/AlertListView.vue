<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { VOICE_ALERT_TYPES, fetchAlerts, fetchCameras, snapshotUrl, type Alert, type Camera } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const typeOptions = computed(() => VOICE_ALERT_TYPES.filter((t) => auth.hasFeature(t.value)))
const loading = ref(false)
const cameras = ref<Camera[]>([])
const cameraId = ref<number | undefined>(undefined)
const alertType = ref<string | undefined>(undefined)

const page = ref(1)
const size = ref(20)
const total = ref(0)
const rows = ref<Alert[]>([])

async function loadCameras() {
  cameras.value = await fetchCameras()
}

async function load() {
  loading.value = true
  try {
    const res = await fetchAlerts({
      cameraId: cameraId.value,
      type: alertType.value,
      page: page.value - 1,
      size: size.value,
    })
    rows.value = res.content
    total.value = res.total
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载告警失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCameras()
  await load()
})

watch([cameraId, alertType], async () => {
  page.value = 1
  await load()
})

watch([page, size], async () => {
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="cameraId" clearable placeholder="相机（全部）" style="width: 320px" filterable>
        <el-option v-for="c in cameras" :key="c.id" :label="`${c.name} (#${c.id})`" :value="c.id" />
      </el-select>

      <el-select v-model="alertType" clearable placeholder="告警类型" style="width: 220px">
        <el-option
          v-for="t in typeOptions"
          :key="t.value"
          :label="`${t.label} ${t.value}`"
          :value="t.value"
        />
      </el-select>

      <el-button @click="load" :loading="loading">查询</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="90" />
      <el-table-column prop="cameraId" label="相机" width="100" />
      <el-table-column prop="alertType" label="类型" width="160" />
      <el-table-column prop="score" label="得分" width="90" />
      <el-table-column v-if="auth.isSuperAdmin" label="截图" width="120">
        <template #default="{ row }">
          <el-image
            v-if="snapshotUrl(row.snapshotPath)"
            :src="snapshotUrl(row.snapshotPath)!"
            :preview-src-list="[snapshotUrl(row.snapshotPath)!]"
            fit="cover"
            style="width: 96px; height: 54px"
          />
          <span v-else class="muted">{{ row.snapshotPath || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="时间" width="200" />
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
      />
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
