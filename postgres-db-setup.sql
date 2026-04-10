--
-- PostgreSQL database dump
--

\restrict ly9OqjhEjVDWB56bQu5duJhIfLE3MlC1FYFWtBs88O5bTsImDzcg2mvAII0CgwG

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

-- Started on 2026-04-10 01:51:50

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 4 (class 2615 OID 2200)
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- TOC entry 5046 (class 0 OID 0)
-- Dependencies: 4
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 222 (class 1259 OID 16431)
-- Name: games; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games (
    id integer NOT NULL,
    alpha_players bigint[],
    bravo_players bigint[],
    mode text,
    host bigint,
    score integer[],
    start_date timestamp with time zone,
    end_date timestamp with time zone,
    submit_time timestamp with time zone,
    game_active boolean DEFAULT true,
    admin_locked boolean DEFAULT false,
    game_maps text[],
    game_modes text[],
    alpha_ratings double precision[],
    alpha_deviations double precision[],
    alpha_volatilities double precision[],
    bravo_ratings double precision[],
    bravo_deviations double precision[],
    bravo_volatilities double precision[]
);


--
-- TOC entry 221 (class 1259 OID 16430)
-- Name: games_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.games_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 5047 (class 0 OID 0)
-- Dependencies: 221
-- Name: games_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.games_id_seq OWNED BY public.games.id;


--
-- TOC entry 219 (class 1259 OID 16400)
-- Name: modes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.modes (
    internal_name text NOT NULL,
    name text NOT NULL,
    status integer DEFAULT '-1'::integer NOT NULL,
    description_brief text,
    description text,
    image_url text,
    thumbnail text,
    emoji_id bigint,
    play_all_games boolean DEFAULT false,
    last_rating_period timestamp with time zone,
    rating_period_hours integer DEFAULT 168,
    sort_order integer,
    games integer,
    maplist text,
    format text[]
);


--
-- TOC entry 220 (class 1259 OID 16417)
-- Name: queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.queue (
    modes text[] NOT NULL,
    player_count integer NOT NULL,
    player_ids bigint[] NOT NULL,
    join_date timestamp with time zone NOT NULL,
    available boolean DEFAULT true NOT NULL,
    id integer NOT NULL
);


--
-- TOC entry 223 (class 1259 OID 16443)
-- Name: queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- TOC entry 5048 (class 0 OID 0)
-- Dependencies: 223
-- Name: queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.queue_id_seq OWNED BY public.queue.id;


--
-- TOC entry 225 (class 1259 OID 16461)
-- Name: ratings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ratings (
    user_id bigint NOT NULL,
    mode text NOT NULL,
    rating double precision,
    deviation double precision,
    volatility double precision,
    rating_list double precision[] DEFAULT '{}'::double precision[],
    deviation_list double precision[] DEFAULT '{}'::double precision[],
    outcome_list integer[] DEFAULT '{}'::integer[],
    rating_initial double precision,
    deviation_initial double precision,
    volatility_initial double precision
);


--
-- TOC entry 224 (class 1259 OID 16453)
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    user_id bigint CONSTRAINT user_user_id_not_null NOT NULL,
    host_pref integer,
    register_date timestamp with time zone,
    friend_code text,
    queue_disable_time timestamp with time zone,
    last_played timestamp with time zone
);


--
-- TOC entry 4878 (class 2604 OID 16434)
-- Name: games id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games ALTER COLUMN id SET DEFAULT nextval('public.games_id_seq'::regclass);


--
-- TOC entry 4877 (class 2604 OID 16444)
-- Name: queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.queue ALTER COLUMN id SET DEFAULT nextval('public.queue_id_seq'::regclass);


--
-- TOC entry 4889 (class 2606 OID 16441)
-- Name: games games_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_pkey PRIMARY KEY (id);


--
-- TOC entry 4885 (class 2606 OID 16410)
-- Name: modes modes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.modes
    ADD CONSTRAINT modes_pkey PRIMARY KEY (internal_name);


--
-- TOC entry 4887 (class 2606 OID 16452)
-- Name: queue queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.queue
    ADD CONSTRAINT queue_pkey PRIMARY KEY (id);


--
-- TOC entry 4893 (class 2606 OID 16469)
-- Name: ratings ratings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings
    ADD CONSTRAINT ratings_pkey PRIMARY KEY (user_id, mode);


--
-- TOC entry 4891 (class 2606 OID 16460)
-- Name: users user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT user_pkey PRIMARY KEY (user_id);


-- Completed on 2026-04-10 01:51:50

--
-- PostgreSQL database dump complete
--

\unrestrict ly9OqjhEjVDWB56bQu5duJhIfLE3MlC1FYFWtBs88O5bTsImDzcg2mvAII0CgwG

