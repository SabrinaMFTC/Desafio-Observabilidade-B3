import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  vus: 50,
  duration: '5m',
};

// Mesmas músicas do CATALOG do music-catalog: uma música fora dele geraria 404.
const TRACKS = [
  { artist: 'Foo Fighters', title: 'Everlong' },
  { artist: 'Avicii', title: 'Levels' },
  { artist: 'Massive Attack', title: 'Teardrop' },
];

export default function () {
  const track = TRACKS[Math.floor(Math.random() * TRACKS.length)];
  const artist = encodeURIComponent(track.artist);
  const title = encodeURIComponent(track.title);
  http.get(`http://api:8080/live-sync/track?artist=${artist}&title=${title}`);
  sleep(0.1);
}