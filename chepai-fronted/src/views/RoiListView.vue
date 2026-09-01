<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createRoi, fetchCameras, fetchRois, type Camera, type RoiRegion } from '@/api/client'

const loading = ref(false)
const cameras = ref<Camera[]>([])
const cameraId = ref<number | null>(null)
const rows = ref<RoiRegion[]>([])

const dialog = ref(false)
const form = ref({
  regionType: 'parking',
  name: '',
  polygonJson: JSON.stringify(
    [
      [0.1, 0.1],
      [0.9, 0.1],
      [0.9, 0.9],
      [0.1, 0.9],
    ],
    null,
    2,
  ),
})

async function loadCameras() {
  cameras.value = await fetchCameras()
  if (!cameraId.value && cameras.value.length > 0) {
    cameraId.value = cameras.value[0]!.id
  }
}

async function loadRois() {
  if (!cameraId.value) {
    rows.value = []
    return
  }
  loading.value = true
  try {
    rows.value = await fetchRois(cameraId.value)
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!cameraId.value) {
    ElMessage.warning('请选择相机')
    return
  }
  if (!form.value.regionType) {
    ElMessage.warning('请选择区域类型')
    return
  }
  try {
    JSON.parse(form.value.polygonJson)
  } catch {
    ElMessage.error('polygonJson 必须是合法 JSON')
    return
  }

  await createRoi({
    cameraId: cameraId.value,
    regionType: form.value.regionType,
    name: form.value.name || null,
    polygonJson: form.value.polygonJson,
  })
  ElMessage.success('已创建')
  dialog.value = false
  await loadRois()
}

onMounted(async () => {
  await loadCameras()
  await loadRois()
})

watch(cameraId, async () => {
  await loadRois()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="cameraId" placeholder="相机" style="width: 360px" filterable>
        <el-option v-for="c in cameras" :key="c.id" :label="`${c.name} (#${c.id})`" :value="c.id" />
      </el-select>
      <el-button type="primary" @click="dialog = true" :disabled="!cameraId">新建 ROI</el-button>
      <el-button @click="loadRois" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="90" />
      <el-table-column prop="regionType" label="类型" width="120" />
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="polygonJson" label="多边形 JSON" min-width="240" show-overflow-tooltip />
      <el-table-column prop="createdAt" label="创建时间" width="200" />
    </el-table>

    <el-dialog v-model="dialog" title="新建 ROI" width="720px" destroy-on-close>
      <el-form label-width="120px">
        <el-form-item label="区域类型" required>
          <el-select v-model="form.regionType" style="width: 240px">
            <el-option label="车位 parking" value="parking" />
            <el-option label="充电桩 pile" value="pile" />
            <el-option label="全幅 full" value="full" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="polygonJson" required>
          <el-input v-model="form.polygonJson" type="textarea" :rows="8" />
          <div class="hint">存 JSON 数组或对象；可与边缘侧约定归一化坐标或像素坐标。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
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
.hint {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
