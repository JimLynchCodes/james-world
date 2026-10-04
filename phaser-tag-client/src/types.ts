export type UUID = string;

export type PlayerState = {
  id: UUID;
  x: number;
  y: number;
  energy: number;
  is_running: boolean;
  is_it: boolean;
  is_bot: boolean;
  facing: number;
};