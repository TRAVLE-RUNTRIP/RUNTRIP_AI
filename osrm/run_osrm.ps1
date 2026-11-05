# OSRM 도보 경로 서버를 Docker로 띄웁니다. 처음 한 번은 지도 전처리(약 10~30분), 다음부턴 바로 실행.
# 사용: 런트립 폴더에서  powershell -ExecutionPolicy Bypass -File osrm\run_osrm.ps1
# 확인: http://localhost:5000/route/v1/foot/126.9918,37.5704;126.9850,37.5820
# EC2에도 같은 이미지·같은 명령으로 그대로 옮길 수 있습니다.
$ErrorActionPreference = "Stop"
$img  = "ghcr.io/project-osrm/osrm-backend:v5.27.1"
$data = $PSScriptRoot
$name = "south-korea-latest"

if (-not (Test-Path (Join-Path $data "$name.osm.pbf"))) { throw "$name.osm.pbf 가 없습니다. geofabrik에서 받아 osrm 폴더에 두세요." }

if (-not (Test-Path (Join-Path $data "$name.osrm.mldgr"))) {          # 전처리 결과가 없을 때만
    # foot.lua = 기본 도보 프로필에서 페리만 뺀 것. 프로필을 바꾸면 .osrm* 파일을 지우고 다시 실행
    foreach ($step in @("osrm-extract -p /data/foot.lua /data/$name.osm.pbf",
                        "osrm-partition /data/$name.osrm",
                        "osrm-customize /data/$name.osrm")) {
        Write-Host ">> $step"
        docker run --rm -t -v "${data}:/data" $img $step.Split(" ")
        if ($LASTEXITCODE -ne 0) { throw "실패: $step (메모리 부족이면 Docker Desktop > Settings > Resources에서 메모리를 늘리세요)" }
    }
}

docker rm -f osrm-foot 2>$null | Out-Null
docker run -d --name osrm-foot --restart unless-stopped -p 5000:5000 -v "${data}:/data" $img osrm-routed --algorithm mld /data/$name.osrm
if ($LASTEXITCODE -ne 0) { throw "서버 실행 실패" }
Write-Host "OSRM 도보 서버 실행 중: http://localhost:5000"
