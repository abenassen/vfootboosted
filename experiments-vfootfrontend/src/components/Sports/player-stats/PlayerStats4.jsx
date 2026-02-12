import { StarIcon } from '@heroicons/react/20/solid';

const data = {
  metrics: [
    {
      label: 'Birthdate',
      value: '02/23/98',
    },
    {
      label: 'HT / WT',
      value: '6\' 5", 195 lbs',
    },
    {
      label: 'From',
      value: 'OR, USA',
      flag: 'us',
    },
  ],
  performances: [
    {
      label: 'Accuracy',
      rating: 5,
    },
    {
      label: 'Speed',
      rating: 4,
    },
    {
      label: 'Stamina',
      rating: 5,
    },
  ],
  statistics: [
    {
      label: 'Position',
      value: 'FW',
    },
    {
      label: 'Years',
      value: 24,
    },
    {
      label: 'Shirt #',
      value: 26,
    },
    {
      label: 'Wins',
      value: 17,
    },
    {
      label: 'Losses',
      value: 9,
    },
    {
      label: 'Points',
      value: 401,
    },
  ],
  leagues: [
    {
      title: 'SportyBlocks League A',
      seasons: [
        {
          year: '2022',
          team: {
            name: 'Golden Team',
            color: 'text-team-golden-primary',
          },
          stats: {
            wins: 22,
            losses: 2,
            draws: 7,
            turnovers: 5.2,
            diff: 7,
            st1: 67,
            st2: 12,
            st3: 9,
            st4: 11,
            st5: 73,
            st6: 30,
            points: 19,
          },
        },
        {
          year: '2021',
          team: {
            name: 'Golden Team',
            color: 'text-team-golden-primary',
          },
          stats: {
            wins: 16,
            losses: 8,
            draws: 4,
            turnovers: 2.7,
            diff: 14,
            st1: 26,
            st2: 19,
            st3: 13,
            st4: 45,
            st5: 18,
            st6: 22,
            points: 11,
          },
        },
        {
          year: '2020',
          team: {
            name: 'Emerald Team',
            color: 'text-team-emerald-primary',
          },
          stats: {
            wins: 5,
            losses: 1,
            draws: 3,
            turnovers: 0.8,
            diff: 8,
            st1: 43,
            st2: 30,
            st3: 7,
            st4: 28,
            st5: 11,
            st6: 9,
            points: 7,
          },
        },
        {
          year: 'Total',
          stats: {
            wins: 42,
            losses: 11,
            draws: 14,
            turnovers: 7.7,
            diff: 29,
            st1: 136,
            st2: 61,
            st3: 29,
            st4: 84,
            st5: 101,
            st6: 61,
            points: 37,
          },
        },
      ],
    },
    {
      title: 'World League Tournament',
      seasons: [
        {
          year: '2022',
          team: {
            name: 'Golden Team',
            color: 'text-team-golden-primary',
          },
          stats: {
            wins: 22,
            losses: 2,
            draws: 7,
            turnovers: 5.2,
            diff: 7,
            st1: 67,
            st2: 12,
            st3: 9,
            st4: 11,
            st5: 73,
            st6: 30,
            points: 19,
          },
        },
        {
          year: '2021',
          team: {
            name: 'Golden Team',
            color: 'text-team-golden-primary',
          },
          stats: {
            wins: '-',
            losses: '-',
            draws: '-',
            turnovers: '-',
            diff: '-',
            st1: '-',
            st2: '-',
            st3: '-',
            st4: '-',
            st5: '-',
            st6: '-',
            points: '-',
          },
        },
        {
          year: '2020',
          team: {
            name: 'Emerald Team',
            color: 'text-team-emerald-primary',
          },
          stats: {
            wins: 5,
            losses: 1,
            draws: 3,
            turnovers: 0.8,
            diff: 8,
            st1: 43,
            st2: 30,
            st3: 7,
            st4: 28,
            st5: 11,
            st6: 9,
            points: 7,
          },
        },
        {
          year: 'Total',
          stats: {
            wins: 26,
            losses: 3,
            draws: 10,
            turnovers: 6.0,
            diff: 15,
            st1: 110,
            st2: 42,
            st3: 16,
            st4: 39,
            st5: 84,
            st6: 37,
            points: 26,
          },
        },
      ],
    },
  ],
};

function classNames(...classes) {
  return classes.filter(Boolean).join(' ');
}

export default function PlayerStats4() {
  return (
    <div className="mx-auto w-full max-w-[1100px] px-5">
      <div className="@container grid gap-5">
        <div className="rounded-3xl border border-custom-gray-200 bg-white px-5 @4xl:px-8 dark:border-custom-gray-600 dark:bg-custom-gray-800">
          <div className="grid grid-cols-[140px_1fr] overflow-hidden @-3xl:grid-cols-[140px_1fr_1fr] @-3xl:grid-rows-[repeat(3,auto)] @-4xl:grid-cols-[240px_1fr_1fr] @-5xl:grid-cols-[360px_1fr_210px] @-5xl:grid-rows-[auto_auto] @5xl:gap-y-4">
            <div className="@3xl:col-span-1 @3xl:col-start-1 @3xl:row-span-2 @3xl:row-start-1">
              <div className="relative isolate flex h-full min-h-[140px] overflow-hidden @4xl:min-h-[180px] @5xl:min-h-[338px] @5xl:overflow-visible">
                <img
                  src="https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-1.png"
                  alt="Player"
                  className="absolute start-1/2 top-0 w-[180px] max-w-[380px] -translate-x-1/2 @5xl:w-[380px]"
                />
                <div className="absolute inset-0 -z-10 bg-linear-to-b from-custom-orange to-custom-yellow [clip-path:polygon(0_0,_76%_0,_100%_100%,_24%_100%)] @5xl:end-3">
                  <div className="absolute -inset-y-2 end-6 w-1 -rotate-[13.5deg] bg-white @lg:w-1.5 @4xl:end-10 @4xl:-rotate-[19deg] @5xl:end-[60px] @5xl:-rotate-[14deg] dark:bg-custom-gray-800"></div>
                  <svg
                    viewBox="0 0 420 420"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className="absolute start-0 top-5 h-20 w-20 text-team-golden-primary @4xl:h-32 @4xl:w-32 @5xl:h-52 @5xl:w-52"
                  >
                    <path
                      d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                      fill="currentColor"
                    />
                    <path
                      d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                      className="fill-custom-gray-900"
                    />
                    <path
                      d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                      className="fill-white"
                    />
                    <path
                      fillRule="evenodd"
                      clipRule="evenodd"
                      d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                      fill="currentColor"
                    />
                    <path
                      d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                      className="fill-white"
                    />
                  </svg>
                </div>
              </div>
            </div>
            <div className="py-5 ps-3 @3xl:col-span-1 @3xl:col-start-2 @3xl:row-span-2 @3xl:row-start-1 @5xl:row-span-1 @5xl:-ms-2 @5xl:ps-0 @5xl:pt-10 @5xl:pb-0">
              <h2 className="mb-2 grid text-lg/none font-extrabold tracking-[-0.06em] text-custom-gray-900 @4xl:text-xl/none @5xl:mb-1 @5xl:text-2xl/none dark:text-white">
                <span>James</span>
                <span className="-mt-2 truncate text-3xl/tight tracking-[-0.07em] @4xl:text-4xl/tight @5xl:-mt-4 @5xl:text-[4.25rem]/tight">
                  Sporty
                </span>
              </h2>
              <div>
                <span className="inline-flex items-center gap-x-1 rounded-full border border-custom-gray-200 px-2 py-1 text-[0.6875rem]/none font-bold uppercase @lg:gap-x-1.5 @5xl:px-3 @5xl:py-1.5 @5xl:text-xs/normal dark:border-custom-gray-600">
                  <svg
                    viewBox="0 0 420 420"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-3 w-3 shrink-0 self-start text-team-golden-primary @lg:h-4 @lg:w-4 @5xl:self-center"
                  >
                    <path
                      d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                      fill="currentColor"
                    />
                    <path
                      d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                      className="fill-custom-gray-900"
                    />
                    <path
                      d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                      className="fill-white"
                    />
                    <path
                      fillRule="evenodd"
                      clipRule="evenodd"
                      d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                      fill="currentColor"
                    />
                    <path
                      d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                      className="fill-white"
                    />
                  </svg>
                  Golden Team
                </span>
              </div>
            </div>
            <div className="col-span-full grid gap-y-6 py-5 @3xl:col-span-1 @3xl:col-start-3 @3xl:row-span-2 @3xl:row-start-1 @3xl:place-content-center @5xl:col-span-2 @5xl:col-start-2 @5xl:row-span-1 @5xl:row-start-2 @5xl:gap-y-7 @5xl:ps-8 @5xl:pt-0 @5xl:@3xl:place-content-start">
              <div className="grid gap-4 @sm:grid-cols-3 @5xl:gap-6">
                {data.metrics.map((metric) => (
                  <div
                    key={metric.label}
                    className="flex flex-row-reverse justify-between gap-y-1.5 text-custom-gray-900 uppercase @sm:flex-col dark:text-white"
                  >
                    <div className="inline-flex items-center gap-x-1 text-sm/none font-bold @5xl:gap-x-1.5">
                      {metric.flag && (
                        <svg
                          viewBox="0 0 22 22"
                          fill="none"
                          xmlns="http://www.w3.org/2000/svg"
                          className="h-2 w-2 rounded-full @5xl:h-2.5 @5xl:w-2.5"
                        >
                          <rect width="22" height="22" rx="11" fill="white" />
                          <path fillRule="evenodd" clipRule="evenodd" d="M0 0H13.2V10.2667H0V0Z" fill="#1A47B8" />
                          <path
                            fillRule="evenodd"
                            clipRule="evenodd"
                            d="M13.2 0V1.46667H30.8V0H13.2ZM13.2 2.93333V4.4H30.8V2.93333H13.2ZM13.2 5.86667V7.33333H30.8V5.86667H13.2ZM13.2 8.8V10.2667H30.8V8.8H13.2ZM0 11.7333V13.2H30.8V11.7333H0ZM0 14.6667V16.1333H30.8V14.6667H0ZM0 17.6V19.0667H30.8V17.6H0ZM0 20.5333V22H30.8V20.5333H0Z"
                            fill="#F93939"
                          />
                          <path
                            fillRule="evenodd"
                            clipRule="evenodd"
                            d="M1.46667 1.46667V2.93333H2.93334V1.46667H1.46667ZM4.40001 1.46667V2.93333H5.86667V1.46667H4.40001ZM7.33334 1.46667V2.93333H8.80001V1.46667H7.33334ZM10.2667 1.46667V2.93333H11.7333V1.46667H10.2667ZM8.80001 2.93333V4.4H10.2667V2.93333H8.80001ZM5.86667 2.93333V4.4H7.33334V2.93333H5.86667ZM2.93334 2.93333V4.4H4.40001V2.93333H2.93334ZM1.46667 4.4V5.86667H2.93334V4.4H1.46667ZM4.40001 4.4V5.86667H5.86667V4.4H4.40001ZM7.33334 4.4V5.86667H8.80001V4.4H7.33334ZM10.2667 4.4V5.86667H11.7333V4.4H10.2667ZM1.46667 7.33333V8.8H2.93334V7.33333H1.46667ZM4.40001 7.33333V8.8H5.86667V7.33333H4.40001ZM7.33334 7.33333V8.8H8.80001V7.33333H7.33334ZM10.2667 7.33333V8.8H11.7333V7.33333H10.2667ZM8.80001 5.86667V7.33333H10.2667V5.86667H8.80001ZM5.86667 5.86667V7.33333H7.33334V5.86667H5.86667ZM2.93334 5.86667V7.33333H4.40001V5.86667H2.93334Z"
                            fill="white"
                          />
                        </svg>
                      )}
                      {metric.value}
                    </div>
                    <div className="text-[0.6875rem]/none">{metric.label}</div>
                  </div>
                ))}
              </div>
              <div className="grid gap-4 @sm:grid-cols-3 @5xl:gap-6">
                {data.performances.map((performance) => (
                  <div key={performance.label} className="flex flex-row-reverse justify-between @sm:flex-col @sm:gap-2">
                    <div className="flex items-center gap-1">
                      {[0, 1, 2, 3, 4].map((rating) => (
                        <StarIcon
                          key={rating}
                          className={classNames(
                            performance.rating > rating ? 'text-team-golden-secondary' : 'text-custom-gray-200 dark:text-custom-gray-600',
                            'h-2.5 w-2.5 shrink-0',
                          )}
                          aria-hidden="true"
                        />
                      ))}
                    </div>
                    <div className="text-[0.6875rem]/tight uppercase">{performance.label}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="col-span-full pb-5 @3xl:pt-5 @5xl:col-span-1 @5xl:col-start-3 @5xl:row-span-2 @5xl:row-start-1 @5xl:pt-10">
              <div className="grid grid-cols-2 gap-4 @sm:grid-cols-3 @3xl:grid-cols-6 @5xl:grid-cols-2">
                {data.statistics.map((statistic) => (
                  <div
                    key={statistic.label}
                    className="group flex flex-col items-center justify-center gap-1 rounded-2xl border border-custom-gray-200 bg-custom-gray-100 px-3 py-4 text-custom-gray-900 uppercase first:bg-team-golden-secondary first:text-white @5xl:py-5 dark:border-custom-gray-600 dark:bg-custom-gray-700 dark:text-white"
                  >
                    <div className="text-sm/tight font-bold">{statistic.value}</div>
                    <div className="text-[0.6875rem]/tight group-first:font-bold">{statistic.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="overflow-hidden rounded-3xl border border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
          {data.leagues.map((league) => (
            <div key={league.title} className="group overflow-x-auto rounded-t-3xl bg-team-golden-secondary">
              <div className="text-white group-even:rounded-t-3xl">
                <h4 className="px-5 pt-4 pb-8 text-xs/tight font-bold uppercase @4xl:px-8">{league.title}</h4>
              </div>
              <div className="-mt-4 min-w-full rounded-3xl ring-1 ring-custom-gray-200 dark:ring-custom-gray-600">
                <table className="w-full border-collapse border-spacing-px rounded-3xl bg-custom-gray-100 text-custom-gray-900 dark:bg-custom-gray-700 dark:text-white">
                  <thead className="text-xs/tight font-bold uppercase">
                    <tr>
                      <th scope="col" className="py-3.5 ps-8 pe-4 text-start">
                        Season
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-start">
                        Team
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        w
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        l
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        d
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        t
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        diff
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st1
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st2
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st3
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st4
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st5
                      </th>
                      <th scope="col" className="px-2.5 py-3.5 text-center">
                        st6
                      </th>
                      <th scope="col" className="py-3.5 ps-1 pe-8 text-end">
                        pts
                      </th>
                    </tr>
                  </thead>
                  <tbody className="rounded-3xl text-sm/tight font-bold text-custom-gray-900 ring-1 ring-custom-gray-200 dark:text-white dark:ring-custom-gray-600">
                    {league.seasons.map((row) => (
                      <tr
                        key={row.year}
                        className="first:rounded-t-3xl [&_td]:bg-white dark:[&_td]:border-custom-gray-600 dark:[&_td]:bg-custom-gray-800 [&:first-child>td:first-child]:rounded-ss-3xl [&:first-child>td:last-child]:rounded-se-3xl [&:last-child>td]:bg-custom-gray-100 dark:[&:last-child>td]:bg-custom-gray-700 [&>td]:border-b [&>td]:border-custom-gray-200"
                      >
                        <td className="py-4 ps-8 pe-4 text-start">{row.year}</td>

                        <td className="px-4 py-4 text-start whitespace-nowrap">
                          {row.team && (
                            <div className="flex items-center gap-1.5">
                              <svg
                                viewBox="0 0 420 420"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                                className={`h-6 w-6 shrink-0 ${row.team.color}`}
                              >
                                <path
                                  d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                                  fill="currentColor"
                                />
                                <path
                                  d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                                  className="fill-custom-gray-900"
                                />
                                <path
                                  d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                                  className="fill-white"
                                />
                                <path
                                  fillRule="evenodd"
                                  clipRule="evenodd"
                                  d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                                  fill="currentColor"
                                />
                                <path
                                  d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                                  className="fill-white"
                                />
                              </svg>
                              <div className="w-24 min-w-0 flex-1 truncate">{row.team.name}</div>
                            </div>
                          )}
                        </td>
                        <td className="px-2.5 py-4 text-center">{row.stats.wins}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.losses}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.draws}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.turnovers}</td>
                        <td className="px-2.5 py-4 text-center font-normal text-custom-gray dark:text-custom-gray-400">{row.stats.diff}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.st1}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.st2}</td>
                        <td className="px-2.5 py-4 text-center font-normal text-custom-gray dark:text-custom-gray-400">{row.stats.st3}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.st4}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.st5}</td>
                        <td className="px-2.5 py-4 text-center">{row.stats.st6}</td>
                        <td className="py-4 pe-8 text-end">{row.stats.points}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
