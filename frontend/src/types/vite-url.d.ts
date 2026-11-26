// Vite 가 `?url` 로 가져온 파일을 배포 경로 문자열로 바꿔 준다(PDF.js 작업자 파일).
declare module '*?url' {
  const src: string
  export default src
}
